import worlds._bizhawk as bizhawk
from . import client_data
from worlds._bizhawk.client import BizHawkClient

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
        return True

    async def game_watcher(self, ctx):
        
        # Handle the case that if game_watcher is None, continue and don't crash
        if ctx.server is None or ctx.server.socket.closed or ctx.slot_data is None:
            return
        
        starting_mission = get_starting_mission(ctx)

        unlock_block = build_mission_unlock_block(ctx, starting_mission)

        # bizhawk.write expects: (ctx.bizhawk_ctx, [(address, data, domain)])
        # await pauses this function until the write completes

        # Update unlocked levels in game
        await bizhawk.write(ctx.bizhawk_ctx, [(UNLOCK_BASE_ADDRESS, unlock_block, "RDRAM"),]) 


        
