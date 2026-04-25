import worlds._bizhawk as bizhawk
import logging
from . import client_data
from worlds._bizhawk.client import BizHawkClient

# Debug
logger = logging.getLogger("Client")

# Core GoldenEye RAM addresses used by the client runtime.
SCREEN_ID_ADDRESS = 0x2A8C0
MISSION_ID_ADDRESS = 0x2A8F8
DIFFICULTY_ADDRESS = 0x2A8FC
UNLOCK_BASE_ADDRESS = 0x7F000
OBJECTIVE_FLAG_BASE_ADDRESS = 0x75D58
OBJECTIVE_FLAG_BLOCK_SIZE = 40

MISSIONS = client_data.MISSIONS
MISSION_BY_ID = client_data.MISSION_BY_ID
MISSION_BY_UNLOCK_ITEM_ID = client_data.MISSION_BY_UNLOCK_ITEM_ID
MISSION_BY_STARTING_OPTION_VALUE = client_data.MISSION_BY_STARTING_OPTION_VALUE

FAILED_ABORTED_ADDRESS = 0x2A924
BOND_KIA_ADDRESS = 0x2A928
SCREEN_MISSION_DEBRIEF = 0x0C

def get_starting_mission(ctx):
    starting_mission_value = ctx.slot_data["options"]["starting_mission"]
    return MISSION_BY_STARTING_OPTION_VALUE[starting_mission_value]

# Mission Unlocks - a list of 0's that turn to 1 when that level is unlocked

def build_mission_unlock_block(ctx, starting_mission):
    unlock_block = []
    for i in range(len(MISSIONS)):
        unlock_block.append(0)
    
    unlock_block[starting_mission["unlock_byte_offset"]] = 1 # Apply starting mission
    
    # The live loop to accept new unlocked levels and add them to unlock_block
    for item in ctx.items_received:
        if item.item in MISSION_BY_UNLOCK_ITEM_ID: # item.item is the AP item id number
            mission = MISSION_BY_UNLOCK_ITEM_ID[item.item]
            byte = mission["unlock_byte_offset"]
            unlock_block[byte] = 1
    
    return unlock_block

# Objective and Mission Completes

def get_active_objective_checks(ctx, mission, difficulty_code):
    if ctx.slot_data["options"]["objective_mode"] == 2: # player chose shared objectives index [2]
        return mission["shared_objective_checks"]
    return mission["objective_checks_per_difficulty"][difficulty_code] # player chose per difficulty objectives

def get_active_clear_location_id(ctx, mission, difficulty_code):
    if ctx.slot_data["options"]["mission_clear_mode"] == 2: # player chose shared mission difficulty index [2]
        return mission["shared_clear_location_id"]
    return mission["clear_location_ids"][difficulty_code] # player chose per difficulty clear

class GoldeneyeClient(BizHawkClient):
    game = "GoldenEye 007"
    system = "N64"
    patch_suffix = ".apge"

    async def validate_rom(self, ctx):
        try:
            title = bytes((await bizhawk.read(ctx.bizhawk_ctx, [(0x20, 20, "ROM")]))[0]).decode(
                "ascii",
                errors="ignore",
            )
        except bizhawk.RequestFailedError:
            return False

        if "GOLDENEYE" not in title.upper():
            return False
        
        # CTX = Client Context Object. A ctx is a live Archipelago client state object that is passed through this code.
        ctx.game = self.game
        ctx.items_handling = 0b111
        ctx.want_slot_data = True

        # Initialize variables and give placeholders
        self.last_debug_mission_id = None
        self.last_debug_difficulty = None
        self.previous_objective_flags = None
        self.previous_objective_mission_id = None
        self.previous_objective_difficulty = None

        self.local_checked_locations = set() # keep track of what's been checked
        self.pending_success_objectives = set() # keep track of success-only objectives

        return True

    async def game_watcher(self, ctx):
        
        # Handle the case that if game_watcher is None, continue and don't crash
        if ctx.server is None or ctx.server.socket.closed or ctx.slot_data is None:
            return
        
        # Sync checked locations from AP
        # update self.local_checked_locations from ctx.locations_checked or ctx.checked_locations so reconnects don’t resend old checks
        checked_locations = getattr(ctx, "locations_checked", None)
        if checked_locations is None:
            checked_locations = getattr(ctx, "checked_locations", None)

        if checked_locations:
            for location_id in checked_locations:
                self.local_checked_locations.add(int(location_id))

        # Get the starting mission from slot_data and build the unlock block
        starting_mission = get_starting_mission(ctx)
        unlock_block = build_mission_unlock_block(ctx, starting_mission)

        #
        # bizhawk.write expects: (ctx.bizhawk_ctx, [(address, data, domain)])
        # await pauses this function until the write completes
        #

        # Update unlocked levels in game
        await bizhawk.write(ctx.bizhawk_ctx, [(UNLOCK_BASE_ADDRESS, unlock_block, "RDRAM"),]) 

        # Read current Bizhawk Values
        reads = await bizhawk.read(ctx.bizhawk_ctx, [       # The list of addresses we want info from
            (SCREEN_ID_ADDRESS, 4, "RDRAM"),                
            (MISSION_ID_ADDRESS, 4, "RDRAM"),
            (DIFFICULTY_ADDRESS, 4, "RDRAM"),
            (FAILED_ABORTED_ADDRESS, 4, "RDRAM"),
            (BOND_KIA_ADDRESS, 4, "RDRAM"),
        ])

        # Set current game state variables
        screen_id = int.from_bytes(reads[0], "big")
        mission_id = int.from_bytes(reads[1], "big")
        selected_difficulty = int.from_bytes(reads[2], "big")
        
        failed_or_aborted = int.from_bytes(reads[3], "big")
        bond_kia = int.from_bytes(reads[4], "big")
        
        mission = MISSION_BY_ID.get(mission_id)
        
        # #  # #  # #  # #  # #  # #  # #  # #  #
        # The LOOP tm for each valid game frame #
        # #  # #  # #  # #  # #  # #  # #  # #  #
        
        # We only want info after a mission and difficulty is selected
        if mission is not None and selected_difficulty in (0, 1, 2): # check if it's a valid frame
            difficulty_code = selected_difficulty + 1

            if mission_id != self.last_debug_mission_id or selected_difficulty != self.last_debug_difficulty:
                self.last_debug_mission_id = mission_id
                self.last_debug_difficulty = selected_difficulty

            if mission is not None:
                active_objectives = get_active_objective_checks(ctx, mission, difficulty_code)
                clear_location_id = get_active_clear_location_id(ctx, mission, difficulty_code)

                ########################
                # | Objective Checks | #
                ########################

                objective_flag_reads = await bizhawk.read(ctx.bizhawk_ctx, [
                    (OBJECTIVE_FLAG_BASE_ADDRESS, OBJECTIVE_FLAG_BLOCK_SIZE, "RDRAM"),
                ])
                objective_flags = objective_flag_reads[0]

                # If the mission changed, create the new objective block

                if (mission_id != self.previous_objective_mission_id                    # if mission_id is not equal to the stored previous_mission ID
                    or selected_difficulty != self.previous_objective_difficulty):      # or difficulty in the case of per difficulty is selected
                    self.pending_success_objectives.clear()                             # Reset pending success objectives set
                    self.previous_objective_mission_id = mission_id                     # change mission_id now that it's changed and
                    self.previous_objective_difficulty = selected_difficulty            # change selected_difficulty now that it's changed and
                    self.previous_objective_flags = objective_flags                     # change objective_id now that it's changed
                    return
                    
                if objective_flags != self.previous_objective_flags:                    # if objective_flags is not equal to the stored objective flag block
                    old_objective_flags = self.previous_objective_flags                 # store old_objective_flags so we wait to update until it changes again
                    self.previous_objective_flags = objective_flags                     # change objective_flags to the current map's objectives

                    for objective in active_objectives:                                 # loop through each of these objectives
                        flag_offset = objective["flag_offset"]                          # get the flag_offset address for this objective
                        flag_byte_offset = flag_offset * 4                              # Objectives addresses are offset by 4 bytes
                        
                        # "Flag Byte Offset" is the start of the objective's 4-byte slot, if flag offset is 3 then the byte offset is 12
                        # We need 4 bytes starting at the right spot (eg. 12, 13, 14 ,15)
                        # Then int.from_bytes ..."big" will turn those bytes into one number, "big" means the leftmost byte is the biggest part
                        # So like 00 00 00 01 will just become 1
                        # then "& 0xFF" is just "keep only the last 8 bits"

                        old_objective_status = int.from_bytes(old_objective_flags[flag_byte_offset:flag_byte_offset + 4], "big") & 0xFF
                        new_objective_status = int.from_bytes(objective_flags[flag_byte_offset:flag_byte_offset + 4], "big") & 0xFF

                        # This concludes the "is the new objective_status we just got different from the old objective_status" block

                        if old_objective_status != 1 and new_objective_status == 1:                           # if the stored old objective flag offset is different now
                            location_id = objective["location_id"]                      # Find that objective's location id
                            if location_id not in self.local_checked_locations:         # local_checked_locations was initiated in validate_rom
                                if objective["requires_success"] is False:              # If the objective is marked false in client_data.py
                                    self.local_checked_locations.add(location_id)       # Add it to checked locations list
                                    await ctx.send_msgs([{                              # Tell AP to send the location check
                                        "cmd": "LocationChecks",
                                        "locations": [location_id]
                                    }])
                                else:
                                    self.pending_success_objectives.add(location_id)                 # This is for objectives like Minimize Casualties (requires_success)
                                    
                # # DEBRIEF BLOCK # #

                if screen_id == SCREEN_MISSION_DEBRIEF and failed_or_aborted == 0 and bond_kia == 0: # If the player didn't fuck it up

                    clear_location_id = get_active_clear_location_id(ctx, mission, difficulty_code)  # Get the mission clear location id
                    location_ids = [clear_location_id]                                               # Start a list of ids to send on success
            
                    for objective in active_objectives:
                        if objective["requires_success"] is True:                                    # Handle requires_success objectives
                            location_id = objective["location_id"]
                            flag_offset = objective["flag_offset"]
                            flag_byte_offset = flag_offset * 4                  # Objectives addresses are offset by 4 bytes

                            # Refer to the above & 0xFF lines for reference on all this shit, this is the status of the objective this frame
                            current_objective_status = int.from_bytes(objective_flags[flag_byte_offset:flag_byte_offset + 4], "big") & 0xFF

                            if location_id in self.pending_success_objectives and current_objective_status == 1:
                                location_ids.append(location_id)                                    # Add the success only objectives to list

                    self.pending_success_objectives.clear()                                          # reset pending success objectives

                    new_location_ids = []                                       # Prepare the "new locations to send" list

                    for location_id in location_ids:
                        if location_id not in self.local_checked_locations:         # Exclude any location_ids already checked
                            new_location_ids.append(location_id)                    # Add this location_id to the new list
                    if len(new_location_ids) > 0:                                   # If there's anything new to add
                        self.local_checked_locations.update(new_location_ids)       # Add it (.update cuz it's a set)
                        await ctx.send_msgs([{                                      # Ship it to AP
                        "cmd": "LocationChecks",
                        "locations": new_location_ids
                    }])
                elif screen_id == SCREEN_MISSION_DEBRIEF:                           # If player did fuck it up
                    self.pending_success_objectives.clear()                         # clear the pending_success_objectives and send fucking nothing
                        