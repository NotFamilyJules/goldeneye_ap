import logging
import struct
import tempfile
import textwrap
import time
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from NetUtils import ClientStatus
import worlds._bizhawk as bizhawk
from worlds._bizhawk.client import BizHawkClient

from .Items import item_table
from .Locations import EXTRA_MISSION_REGIONS, EXTRA_MISSION_SELECTIONS, location_table
from .Options import MissionClearMode, ObjectiveMode
from . import _client_data as client_data_module

if TYPE_CHECKING:
    from worlds._bizhawk.context import BizHawkClientContext

logger = logging.getLogger("Client")

ITEM_ID_TO_OFFSET = client_data_module.ITEM_ID_TO_OFFSET
MISSIONS = client_data_module.MISSIONS
PROGRESSIVE_GUN_ITEM_IDS = client_data_module.PROGRESSIVE_GUN_ITEM_IDS
PROGRESSIVE_GUN_ITEM_NAMES = client_data_module.PROGRESSIVE_GUN_ITEM_NAMES
PROGRESSIVE_GUN_BASE_ITEM_ID = client_data_module.PROGRESSIVE_GUN_BASE_ITEM_ID
# Objective data path:
# 1. codegen.py writes OBJECTIVE_FLAGS_PER_DIFFICULTY and OBJECTIVE_FLAGS_SHARED.
# 2. __init__.py sends objective_mode in slot data.
# 3. This client picks one of the generated tables at runtime.
GENERATED_OBJECTIVE_FLAGS_PER_DIFFICULTY = client_data_module.OBJECTIVE_FLAGS_PER_DIFFICULTY
GENERATED_OBJECTIVE_FLAGS_SHARED = client_data_module.OBJECTIVE_FLAGS_SHARED

# File guide:
# 1. Constants and shared data
# 2. Small helper functions
# 3. GoldeneyeClient main loop
# 4. Objective checks
# 5. Item effects and loadout
# 6. Inventory helpers
# 7. Goal completion

# --- Core GE RAM addresses used every frame ---
SCREEN_ID_ADDR = 0x2A8C0
MISSION_ID_ADDR = 0x2A8F8
DIFFICULTY_ADDR = 0x2A8FC
FAILED_ABORTED_ADDR = 0x02A924
BOND_KIA_ADDR = 0x02A928
BONDDATA_PTR_ADDR = 0x7A0B0
UNLOCK_BASE_ADDR = 0x7F000
COMPLETED_BASE_ADDR = 0x7F020
OBJECTIVE_FLAG_BASE_ADDR = 0x75D58
OBJECTIVE_FLAG_BLOCK_SIZE = 40
CHEAT_ENEMY_ROCKETS_ADDR = 0x696BC
GOLDENEYE_TRAP_ADDR = 0x036444
SCREEN_GAMEPLAY = 0x0B
SCREEN_MISSION_DEBRIEF = 0x0C
LOADOUT_TRIGGER_HOLD_FRAMES = 2

# --- Hand / inventory structure offsets inside BONDdata ---
OFF_HAND_ITEM = 0x800
OFF_HANDS_BASE = 0x870
OFF_INV_HEAD = 0x11E0
OFF_INV_POOL = 0x11E4
OFF_INV_MAX = 0x11E8
OFF_ALL_GUNS = 0x11EC
OFF_EQUIP_CUR = 0x11F0

HAND_SIZE = 0x3AC
HAND_OFF_WEAPONNUM = 0x00
HAND_OFF_WEAPONNUM_WATCH = 0x04
HAND_OFF_PREVIOUS_WEAPON = 0x08
HAND_OFF_NEXT_WEAPON = 0x40

INV_ITEM_NONE = -1
INV_ITEM_WEAPON = 1
INV_ITEM_SIZE = 0x14
ITEM_UNARMED = 0
ITEM_FIST = 1
ITEM_TRIGGER = 30
GUNRIGHT = 0
GUNLEFT = 1
MISSION_STARTUP_PRESERVE_WEAPON_IDS = {
    "Train": {23},
    "Facility": {29, 30},
}

HEALTH_DISPLAY_OFFSET = 0x00DC
ARMOR_DISPLAY_OFFSET = 0x00E0
HEALTH_ACTUAL_OFFSET = 0x2A3C
ARMOR_ACTUAL_OFFSET = 0x2A40
FULL_FLOAT_BYTES = struct.pack(">f", 1.0)
DEATHLINK_SEND_COOLDOWN_SECONDS = 1.0
DEATHLINK_TRIGGER_PATH = Path(tempfile.gettempdir()) / "goldeneye_ap_deathlink.flag"
AP_NOTIFICATION_MAILBOX_STATE_ADDR = 0x07F040
AP_NOTIFICATION_MAILBOX_TEXT_ADDR = 0x07F044
AP_NOTIFICATION_MAILBOX_TEXT_LENGTH = 0x97
AP_NOTIFICATION_MAILBOX_EMPTY = 0
AP_NOTIFICATION_MAILBOX_QUEUED = 1
AP_CHECK_NOTIFICATION_MAILBOX_STATE_ADDR = 0x07F0E0
AP_CHECK_NOTIFICATION_MAILBOX_TEXT_ADDR = 0x07F0E4
AP_CHECK_NOTIFICATION_MAILBOX_TEXT_LENGTH = 0x65
TOP_NOTIFICATION_MAX_LINES = 2
TOP_NOTIFICATION_MAX_CHARS_PER_LINE = 30
BOTTOM_NOTIFICATION_MAX_LINES = 2
BOTTOM_NOTIFICATION_MAX_CHARS_PER_LINE = 28
ITEM_FLAG_PROGRESSION = 0b001
ITEM_FLAG_USEFUL = 0b010
ITEM_FLAG_TRAP = 0b100

# Mission clear metadata generated from the Client + Locations sheets.
MISSION_ID_TO_INFO = {mission["mission_id"]: mission for mission in MISSIONS}
STOPPED_GOLDENEYE_ID = location_table["Stopped Goldeneye"].ap_code

# Handy item-id lookups used by incremental item application.
ITEM_NAME_TO_ID = {
    name: data.ap_code
    for name, data in item_table.items()
    if data.ap_code is not None
}
ITEM_ID_TO_NAME = {
    data.ap_code: name
    for name, data in item_table.items()
    if data.ap_code is not None
}

HUD_AMMO_OFFSET_TO_LIVE_OFFSET = {
    0x0C84: 0x1134,
    0x0C90: 0x113C,
    0x0C9C: 0x1140,
    0x0CA8: 0x1158,
    0x0CB4: 0x115C,
    0x0CC0: 0x1148,
    0x0CD8: 0x1144,
    0x0CE4: 0x1160,
    0x0CF0: 0x1164,
    0x0CFC: 0x114C,
    0x0D08: 0x1154,
    0x0D14: 0x1150,
}


def _normalize_live_ammo_offset(ammo_offset: Optional[int]) -> Optional[int]:
    if ammo_offset is None:
        return None
    return HUD_AMMO_OFFSET_TO_LIVE_OFFSET.get(ammo_offset, ammo_offset)


def _normalize_effect_defs(effect_defs: Dict[int, dict]) -> Dict[int, dict]:
    normalized_defs: Dict[int, dict] = {}
    for item_id, effect_def in effect_defs.items():
        normalized_def = dict(effect_def)
        if "ammo_offset" in normalized_def:
            normalized_def["ammo_offset"] = _normalize_live_ammo_offset(normalized_def.get("ammo_offset"))
        ammo_targets = normalized_def.get("ammo_targets")
        if ammo_targets:
            normalized_def["ammo_targets"] = [
                {
                    **ammo_target,
                    "ammo_offset": _normalize_live_ammo_offset(ammo_target.get("ammo_offset")),
                }
                for ammo_target in ammo_targets
            ]
        normalized_defs[item_id] = normalized_def
    return normalized_defs


ITEM_EFFECT_DEFS = _normalize_effect_defs(client_data_module.ITEM_EFFECT_DEFS)
WEAPON_ITEM_DEFS = {
    item_id: effect_def
    for item_id, effect_def in ITEM_EFFECT_DEFS.items()
    if effect_def.get("effect_type") == "weapon"
}

AP_CONTROLLED_WEAPON_IDS = {
    weapon_def["weapon_id"]
    for weapon_def in WEAPON_ITEM_DEFS.values()
}
for weapon_def in WEAPON_ITEM_DEFS.values():
    for extra_inventory_id in weapon_def.get("extra_inventory_ids", []):
        AP_CONTROLLED_WEAPON_IDS.add(extra_inventory_id)

OBJECTIVE_FLAGS_PER_DIFFICULTY = GENERATED_OBJECTIVE_FLAGS_PER_DIFFICULTY
OBJECTIVE_FLAGS_SHARED = GENERATED_OBJECTIVE_FLAGS_SHARED

# Edit these templates to change the in-game receive text.
AMMO_RECEIVED_NOTIFICATION_TEMPLATE = "{sender}: Found some {item}. I hope you have the gun for it?"
MAGNUM_AMMO_RECEIVED_NOTIFICATION = "{sender}: Dropped my monster bullets, that you can use for your magnum dong."
WEAPON_RECEIVED_NOTIFICATION_TEMPLATE = "{sender}: Here's the {item} for your loadouts."
LEVEL_RECEIVED_NOTIFICATION_TEMPLATE = "{sender}: Just bought you a ticket to {item}!"
DEFAULT_RECEIVED_NOTIFICATION_TEMPLATE = "{sender}: Found this {item}, I think it belongs to you."
PROGRESSION_SENT_CHECK_NOTIFICATION_TEMPLATE = "Picked up {item} for {player}. Seems Important!"
USEFUL_SENT_CHECK_NOTIFICATION_TEMPLATE = "Picked up {item} for {player}. Looks useful!"
TRAP_SENT_CHECK_NOTIFICATION_TEMPLATE = "Picked up {item} for {player}. They're probably not happy about it...."
FILLER_SENT_CHECK_NOTIFICATION_TEMPLATE = "Picked up {item} for {player}. Might not be important..."


def build_objective_location_data(objective_flags: Dict[int, tuple]) -> Dict[int, dict]:
    objective_location_data: Dict[int, dict] = {}
    for ap_code, objective_data in objective_flags.items():
        if len(objective_data) == 3:
            name, addr, map_id = objective_data
        else:
            name, addr = objective_data
            map_id = (ap_code // 100000) % 100

        objective_location_data[ap_code] = {
            "name": name,
            "offset": (addr - OBJECTIVE_FLAG_BASE_ADDR) // 4,
            "map_id": map_id,
            "difficulty_code": (ap_code // 10000) % 10,
            "requires_success": "Minimize " in name,
        }
    return objective_location_data


def build_mission_clear_location_id(map_id: int, difficulty_code: int) -> int:
    return 70000000 + (map_id * 100000) + (difficulty_code * 10000) + 1


OBJECTIVE_LOCATION_DATA_PER_DIFFICULTY = build_objective_location_data(OBJECTIVE_FLAGS_PER_DIFFICULTY)
OBJECTIVE_LOCATION_DATA_SHARED = build_objective_location_data(OBJECTIVE_FLAGS_SHARED)


OBJECTIVE_MODE_PER_DIFFICULTY = ObjectiveMode.option_per_difficulty
OBJECTIVE_MODE_SHARED = ObjectiveMode.option_shared
MISSION_CLEAR_MODE_PER_MAP = MissionClearMode.option_per_map
MISSION_CLEAR_MODE_PER_DIFFICULTY = MissionClearMode.option_per_difficulty


def get_option_value(ctx: "BizHawkClientContext", name: str, default: int):
    # slot_data is created in __init__.py -> fill_slot_data().
    return ctx.slot_data.get("options", {}).get(name, default)


def get_objective_mode(ctx: "BizHawkClientContext") -> int:
    return get_option_value(ctx, "objective_mode", OBJECTIVE_MODE_PER_DIFFICULTY)


def get_mission_clear_mode(ctx: "BizHawkClientContext") -> int:
    return get_option_value(ctx, "mission_clear_mode", MISSION_CLEAR_MODE_PER_MAP)


def is_deathlink_enabled(ctx: "BizHawkClientContext") -> bool:
    return bool(get_option_value(ctx, "death_link", 0))


def is_progressive_gun_unlocks_enabled(ctx: "BizHawkClientContext") -> bool:
    return bool(get_option_value(ctx, "progressive_weapons", 0))


def get_enabled_extra_missions(ctx: "BizHawkClientContext") -> Set[str]:
    option_value = get_option_value(ctx, "extra_locations", 0)
    return set(EXTRA_MISSION_SELECTIONS.get(option_value, set()))


def is_enabled_mission(ctx: "BizHawkClientContext", mission_name: str) -> bool:
    if mission_name not in EXTRA_MISSION_REGIONS:
        return True
    return mission_name in get_enabled_extra_missions(ctx)


def get_mission_clear_location_id(
    mission_info: dict,
    difficulty_code: int,
    mission_clear_mode: int,
) -> int:
    if mission_clear_mode == MISSION_CLEAR_MODE_PER_MAP:
        shared_clear_location_id = mission_info.get("shared_clear_location_id")
        if shared_clear_location_id is not None:
            return shared_clear_location_id
        return build_mission_clear_location_id(mission_info["map_id"], 0)

    clear_location_ids = mission_info.get("clear_location_ids")
    if isinstance(clear_location_ids, dict):
        clear_location_id = clear_location_ids.get(difficulty_code)
        if clear_location_id is not None:
            return clear_location_id

    return build_mission_clear_location_id(mission_info["map_id"], difficulty_code)


def get_all_goal_clear_location_ids(mission_info: dict) -> List[int]:
    clear_location_ids = mission_info.get("clear_location_ids")
    if isinstance(clear_location_ids, dict):
        location_ids = [
            clear_location_ids[difficulty_code]
            for difficulty_code in (1, 2, 3)
            if clear_location_ids.get(difficulty_code) is not None
        ]
        if location_ids:
            return location_ids

    return [
        build_mission_clear_location_id(mission_info["map_id"], difficulty_code)
        for difficulty_code in (1, 2, 3)
    ]


def objective_matches_difficulty(mode: int, objective_difficulty: int, current_difficulty: int) -> bool:
    if mode == OBJECTIVE_MODE_SHARED:
        return True
    return objective_difficulty == current_difficulty


def get_objective_location_data(ctx: "BizHawkClientContext") -> Dict[int, dict]:
    # Shared mode uses the unsuffixed Objective 0 rows from the sheet.
    # Per-difficulty mode uses the explicit Objective 1/2/3 rows from the sheet.
    if get_objective_mode(ctx) == OBJECTIVE_MODE_SHARED:
        return OBJECTIVE_LOCATION_DATA_SHARED
    return OBJECTIVE_LOCATION_DATA_PER_DIFFICULTY


def read_objective_status(raw_flags: bytes, offset: int) -> int:
    return int.from_bytes(raw_flags[offset:offset + 4], "big") & 0xFF


def objective_became_complete(previous_flags: Optional[bytes], current_flags: bytes, offset: int) -> bool:
    if offset < 0 or offset + 4 > len(current_flags):
        return False

    if read_objective_status(current_flags, offset) != 1:
        return False

    if previous_flags is None or offset + 4 > len(previous_flags):
        return True

    return read_objective_status(previous_flags, offset) != 1


def mission_objectives_complete(map_id: int, difficulty_code: int, raw_flags: bytes) -> bool:
    found_objective = False
    for data in OBJECTIVE_LOCATION_DATA_PER_DIFFICULTY.values():
        if data["map_id"] != map_id or data["difficulty_code"] != difficulty_code:
            continue

        found_objective = True
        offset = data["offset"] * 4
        if offset < 0 or offset + 4 > len(raw_flags):
            return False
        if read_objective_status(raw_flags, offset) != 1:
            return False

    return found_objective


def u32_bytes(value: int) -> bytes:
    return int(value & 0xFFFFFFFF).to_bytes(4, "big", signed=False)


def s32_bytes(value: int) -> bytes:
    return int(value).to_bytes(4, "big", signed=True)


def ptr_bytes(value: int) -> bytes:
    if value == 0:
        return b"\x00\x00\x00\x00"
    return u32_bytes(value + 0x80000000)


def get_deathlink_key(death_link) -> Optional[tuple]:
    if not death_link:
        return None
    if isinstance(death_link, dict):
        return (
            death_link.get("time"),
            death_link.get("source"),
            death_link.get("cause"),
        )
    return (str(death_link),)


def get_local_player_name(ctx: "BizHawkClientContext") -> Optional[str]:
    slot = getattr(ctx, "slot", None)
    player_names = getattr(ctx, "player_names", None)
    if slot is None or not isinstance(player_names, dict):
        return None
    return player_names.get(slot)


def clear_deathlink_trigger() -> None:
    try:
        DEATHLINK_TRIGGER_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def arm_deathlink_trigger() -> bool:
    try:
        DEATHLINK_TRIGGER_PATH.write_text(str(time.time()), encoding="ascii")
    except OSError:
        return False
    return True


class GoldeneyeClient(BizHawkClient):
    # AP BizHawk registration metadata.
    game = "GoldenEye 007"
    system = "N64"
    patch_suffix = ".apge"

    local_checked_locations: Set[int]
    prev_screen_id: int
    prev_mission_id: int

    # --- Setup ---
    def initialize_client(self):
        self.local_checked_locations = set()
        self.prev_screen_id = -1
        self.prev_mission_id = -1
        self.prev_bond_kia = 0
        self.effect_items_applied = {item_id: 0 for item_id in ITEM_EFFECT_DEFS}
        self.pending_loadout_mission_id: Optional[int] = None
        self.pending_loadout_hold_frames = 0
        self.pending_loadout_last_hand_next = 0
        self.objective_baseline_flags: Optional[bytes] = None
        self.objective_prev_flags: Optional[bytes] = None
        self.objective_tracking_mission_id: Optional[int] = None
        self.objective_tracking_difficulty: Optional[int] = None
        self.pending_success_objectives: Set[int] = set()
        self.pending_deathlink = False
        self.last_processed_deathlink_key: Optional[tuple] = None
        self.awaiting_local_deathlink = False
        self.last_deathlink_send_at = 0.0
        self.notification_mailbox_initialized = False
        self.received_item_index: Optional[int] = None
        self.pending_received_notifications: List[str] = []
        self.pending_checked_location_notifications: List[int] = []
        self.pending_sent_check_notifications: List[str] = []
        clear_deathlink_trigger()

    # --- AP / BizHawk lifecycle ---
    async def validate_rom(self, ctx: "BizHawkClientContext") -> bool:
        try:
            rom_header = (await bizhawk.read(ctx.bizhawk_ctx, [(0x20, 20, "ROM")]))[0]
            game_title = bytes(rom_header).decode("ascii", errors="ignore").strip("\x00").strip()
            if "GOLDENEYE" not in game_title.upper():
                return False
        except (bizhawk.RequestFailedError, UnicodeDecodeError):
            return False

        ctx.game = self.game
        ctx.items_handling = 0b111
        ctx.want_slot_data = True
        self.initialize_client()
        return True

    # --- Main loop ---
    async def game_watcher(self, ctx: "BizHawkClientContext") -> None:
        if ctx.server is None or ctx.server.socket.closed or ctx.slot_data is None:
            return

        if hasattr(ctx, "update_death_link"):
            try:
                await ctx.update_death_link(is_deathlink_enabled(ctx))
            except Exception:
                pass

        try:
            reads = await bizhawk.read(
                ctx.bizhawk_ctx,
                [
                    (SCREEN_ID_ADDR, 4, "RDRAM"),
                    (MISSION_ID_ADDR, 4, "RDRAM"),
                    (DIFFICULTY_ADDR, 4, "RDRAM"),
                    (FAILED_ABORTED_ADDR, 4, "RDRAM"),
                    (BOND_KIA_ADDR, 4, "RDRAM"),
                    (UNLOCK_BASE_ADDR, 20, "RDRAM"),
                    (BONDDATA_PTR_ADDR, 4, "RDRAM"),
                    (AP_NOTIFICATION_MAILBOX_STATE_ADDR, 4, "RDRAM"),
                    (AP_CHECK_NOTIFICATION_MAILBOX_STATE_ADDR, 4, "RDRAM"),
                ],
            )
        except bizhawk.RequestFailedError:
            return

        screen_id = int.from_bytes(reads[0], "big")
        mission_id = int.from_bytes(reads[1], "big")
        selected_difficulty = int.from_bytes(reads[2], "big")
        failed_or_aborted = int.from_bytes(reads[3], "big")
        bond_kia = int.from_bytes(reads[4], "big")
        bonddata_ptr = int.from_bytes(reads[6], "big") - 0x80000000
        mailbox_state = int.from_bytes(reads[7], "big")
        check_mailbox_state = int.from_bytes(reads[8], "big")
        mission_info = MISSION_ID_TO_INFO.get(mission_id)
        in_active_stage = mission_info is not None and screen_id == SCREEN_GAMEPLAY and bonddata_ptr > 0

        mailbox_state, check_mailbox_state = await self._initialize_notification_mailboxes(
            ctx,
            mailbox_state,
            check_mailbox_state,
        )
        self._sync_known_checked_locations(ctx)
        self._queue_received_notifications(ctx)
        self._queue_sent_check_notifications_from_scouts(ctx)

        self._queue_incoming_deathlink(ctx)
        await self._apply_pending_deathlink(in_active_stage, bond_kia)

        if in_active_stage and bond_kia != 0 and self.prev_bond_kia == 0:
            await self._send_bond_deathlink(ctx, mission_info)

        if in_active_stage and (
            self.prev_screen_id != SCREEN_GAMEPLAY
            or mission_id != self.prev_mission_id
            or selected_difficulty != self.objective_tracking_difficulty
        ):
            self.pending_loadout_mission_id = mission_id
            self.pending_loadout_hold_frames = 0
            self.pending_loadout_last_hand_next = 0
            self.objective_baseline_flags = None
            self.objective_prev_flags = None
            self.objective_tracking_mission_id = mission_id
            self.objective_tracking_difficulty = selected_difficulty
            self.pending_success_objectives.clear()

        if (
            screen_id == SCREEN_MISSION_DEBRIEF
            and self.objective_tracking_mission_id is not None
            and self.objective_tracking_difficulty is not None
        ):
            tracked_mission_info = MISSION_ID_TO_INFO.get(self.objective_tracking_mission_id)
            if tracked_mission_info is not None:
                tracked_difficulty = self.objective_tracking_difficulty
                await self._snapshot_objectives(
                    ctx,
                    tracked_mission_info["map_id"],
                    tracked_difficulty + 1,
                )
                await self._check_mission_clear(
                    ctx,
                    tracked_mission_info,
                    screen_id,
                    failed_or_aborted,
                    bond_kia,
                    tracked_difficulty,
                )

        received_counts = self._get_received_item_counts(ctx)

        unlock_writes = self._build_unlock_writes(ctx, received_counts)
        item_effect_writes: List[tuple] = []

        if bonddata_ptr > 0 and screen_id != 0x07:
            item_effect_writes.extend(
                await self._apply_incremental_items(
                    ctx,
                    bonddata_ptr,
                    received_counts,
                    in_active_stage,
                    self.pending_loadout_mission_id == mission_id,
                )
            )

        if in_active_stage:
            await self._check_objectives(ctx, mission_info, selected_difficulty)

            if self.pending_loadout_mission_id == mission_id:
                applied = await self._try_apply_owned_loadout(ctx, bonddata_ptr, received_counts, mission_info)
                if applied:
                    self.pending_loadout_mission_id = None
                    self.pending_loadout_hold_frames = 0
                    self.pending_loadout_last_hand_next = 0

        if item_effect_writes:
            try:
                await bizhawk.write(ctx.bizhawk_ctx, item_effect_writes)
            except bizhawk.RequestFailedError:
                pass

        if unlock_writes:
            try:
                await bizhawk.write(ctx.bizhawk_ctx, unlock_writes)
            except bizhawk.RequestFailedError:
                pass

        mailbox_state = await self._flush_received_notification(ctx, mailbox_state)
        check_mailbox_state = await self._flush_sent_check_notification(ctx, check_mailbox_state)

        await self._check_goal(ctx)

        self.prev_screen_id = screen_id
        self.prev_mission_id = mission_id
        self.prev_bond_kia = bond_kia

    # --- Simple data helpers ---
    def _get_received_item_counts(self, ctx: "BizHawkClientContext") -> Dict[int, int]:
        counts: Dict[int, int] = {}
        for item in ctx.items_received:
            counts[item.item] = counts.get(item.item, 0) + 1

        if not is_progressive_gun_unlocks_enabled(ctx):
            return counts
        if PROGRESSIVE_GUN_BASE_ITEM_ID is None or not PROGRESSIVE_GUN_ITEM_IDS:
            return counts

        progressive_count = min(
            counts.get(PROGRESSIVE_GUN_BASE_ITEM_ID, 0),
            len(PROGRESSIVE_GUN_ITEM_IDS),
        )
        for index, item_id in enumerate(PROGRESSIVE_GUN_ITEM_IDS):
            counts[item_id] = 1 if index < progressive_count else 0
        return counts

    def _sync_known_checked_locations(self, ctx: "BizHawkClientContext") -> None:
        checked_locations = getattr(ctx, "locations_checked", None)
        if checked_locations is None:
            checked_locations = getattr(ctx, "checked_locations", None)

        if checked_locations:
            self.local_checked_locations.update(int(location_id) for location_id in checked_locations)

    def _build_unlock_writes(self, ctx: "BizHawkClientContext", received_counts: Dict[int, int]) -> List[tuple]:
        writes = []
        starting_mission = get_option_value(ctx, "starting_mission", 1)
        writes.append((UNLOCK_BASE_ADDR + (starting_mission - 1), [1], "RDRAM"))

        for item_id, offset in ITEM_ID_TO_OFFSET.items():
            if received_counts.get(item_id, 0) > 0:
                writes.append((UNLOCK_BASE_ADDR + offset, [1], "RDRAM"))

        return writes

    def _queue_incoming_deathlink(self, ctx: "BizHawkClientContext") -> None:
        if not is_deathlink_enabled(ctx):
            self.pending_deathlink = False
            self.awaiting_local_deathlink = False
            clear_deathlink_trigger()
            return

        death_link = getattr(ctx, "last_death_link", None)
        deathlink_key = get_deathlink_key(death_link)
        if deathlink_key is None or deathlink_key == self.last_processed_deathlink_key:
            return

        if isinstance(death_link, dict):
            local_player_name = get_local_player_name(ctx)
            if local_player_name and death_link.get("source") == local_player_name:
                self.last_processed_deathlink_key = deathlink_key
                return

        self.last_processed_deathlink_key = deathlink_key
        self.pending_deathlink = True

    async def _initialize_notification_mailboxes(
        self,
        ctx: "BizHawkClientContext",
        mailbox_state: int,
        check_mailbox_state: int,
    ) -> tuple[int, int]:
        if self.notification_mailbox_initialized:
            return mailbox_state, check_mailbox_state

        try:
            await bizhawk.write(
                ctx.bizhawk_ctx,
                [
                    (AP_NOTIFICATION_MAILBOX_TEXT_ADDR, bytes(AP_NOTIFICATION_MAILBOX_TEXT_LENGTH), "RDRAM"),
                    (AP_NOTIFICATION_MAILBOX_STATE_ADDR, u32_bytes(AP_NOTIFICATION_MAILBOX_EMPTY), "RDRAM"),
                    (
                        AP_CHECK_NOTIFICATION_MAILBOX_TEXT_ADDR,
                        bytes(AP_CHECK_NOTIFICATION_MAILBOX_TEXT_LENGTH),
                        "RDRAM",
                    ),
                    (AP_CHECK_NOTIFICATION_MAILBOX_STATE_ADDR, u32_bytes(AP_NOTIFICATION_MAILBOX_EMPTY), "RDRAM"),
                ],
            )
        except bizhawk.RequestFailedError:
            return mailbox_state, check_mailbox_state

        self.notification_mailbox_initialized = True
        self.received_item_index = len(ctx.items_received)
        self.pending_received_notifications.clear()
        self.pending_checked_location_notifications.clear()
        self.pending_sent_check_notifications.clear()
        return AP_NOTIFICATION_MAILBOX_EMPTY, AP_NOTIFICATION_MAILBOX_EMPTY

    def _queue_received_notifications(self, ctx: "BizHawkClientContext") -> None:
        if not self.notification_mailbox_initialized:
            return

        if self.received_item_index is None:
            self.received_item_index = len(ctx.items_received)
            return

        if len(ctx.items_received) < self.received_item_index:
            self.received_item_index = len(ctx.items_received)
            self.pending_received_notifications.clear()
            return

        while self.received_item_index < len(ctx.items_received):
            network_item = ctx.items_received[self.received_item_index]
            self.received_item_index += 1
            if self._is_self_sent_item(ctx, network_item):
                continue
            self.pending_received_notifications.append(
                self._format_received_notification(ctx, network_item)
            )

    def _format_received_notification(self, ctx: "BizHawkClientContext", network_item) -> str:
        sender_name = self._get_sender_name(ctx, getattr(network_item, "player", None))
        item_id = getattr(network_item, "item", None)
        item_name = ITEM_ID_TO_NAME.get(item_id, f"Item {item_id}")
        effect_type = ITEM_EFFECT_DEFS.get(item_id, {}).get("effect_type")
        if item_id in ITEM_ID_TO_OFFSET:
            template = LEVEL_RECEIVED_NOTIFICATION_TEMPLATE
        elif item_name == "Magnum Rounds":
            template = MAGNUM_AMMO_RECEIVED_NOTIFICATION
        elif effect_type in {"ammo", "multi_ammo"}:
            template = AMMO_RECEIVED_NOTIFICATION_TEMPLATE
        elif effect_type == "weapon":
            template = WEAPON_RECEIVED_NOTIFICATION_TEMPLATE
        else:
            template = DEFAULT_RECEIVED_NOTIFICATION_TEMPLATE

        return self._fit_notification_text(
            template.format(sender=sender_name, item=item_name),
            AP_NOTIFICATION_MAILBOX_TEXT_LENGTH,
            TOP_NOTIFICATION_MAX_CHARS_PER_LINE,
            TOP_NOTIFICATION_MAX_LINES,
        )

    def _queue_sent_check_notifications_from_scouts(self, ctx: "BizHawkClientContext") -> None:
        if not self.notification_mailbox_initialized or not self.pending_checked_location_notifications:
            return

        while self.pending_checked_location_notifications:
            location_id = self.pending_checked_location_notifications[0]
            location_info = self._get_scouted_location_info(ctx, location_id)
            if location_info is None:
                break

            self.pending_checked_location_notifications.pop(0)
            self.pending_sent_check_notifications.append(
                self._format_sent_check_notification(ctx, location_info)
            )

    def _format_sent_check_notification(self, ctx: "BizHawkClientContext", location_info) -> str:
        item_id = getattr(location_info, "item", None)
        recipient_id = getattr(location_info, "player", None)
        item_flags = int(getattr(location_info, "flags", 0) or 0)
        item_name = self._get_item_name(ctx, item_id, recipient_id)
        recipient_name = self._get_sender_name(ctx, recipient_id)

        if item_flags & ITEM_FLAG_TRAP:
            template = TRAP_SENT_CHECK_NOTIFICATION_TEMPLATE
        elif item_flags & ITEM_FLAG_PROGRESSION:
            template = PROGRESSION_SENT_CHECK_NOTIFICATION_TEMPLATE
        elif item_flags & ITEM_FLAG_USEFUL:
            template = USEFUL_SENT_CHECK_NOTIFICATION_TEMPLATE
        else:
            template = FILLER_SENT_CHECK_NOTIFICATION_TEMPLATE

        return self._fit_notification_text(
            template.format(item=item_name, player=recipient_name),
            AP_CHECK_NOTIFICATION_MAILBOX_TEXT_LENGTH,
            BOTTOM_NOTIFICATION_MAX_CHARS_PER_LINE,
            BOTTOM_NOTIFICATION_MAX_LINES,
        )

    def _is_self_sent_item(self, ctx: "BizHawkClientContext", network_item) -> bool:
        own_player_id = self._get_local_player_id(ctx)
        if own_player_id is None:
            return False
        return getattr(network_item, "player", None) == own_player_id

    def _get_local_player_id(self, ctx: "BizHawkClientContext") -> Optional[int]:
        for attr_name in ("slot", "slot_id", "player", "player_id"):
            value = getattr(ctx, attr_name, None)
            if isinstance(value, int):
                return value
        return None

    def _get_sender_name(self, ctx: "BizHawkClientContext", player_id: Optional[int]) -> str:
        if player_id is None:
            return "Someone"

        player_names = getattr(ctx, "player_names", None)
        if player_names is not None:
            try:
                name = player_names[player_id]
                if name:
                    return str(name)
            except Exception:
                pass

            get_name = getattr(player_names, "get", None)
            if callable(get_name):
                try:
                    name = get_name(player_id)
                    if name:
                        return str(name)
                except Exception:
                    pass

        slot_info = getattr(ctx, "slot_info", None)
        if isinstance(slot_info, dict):
            slot = slot_info.get(player_id)
            if slot is not None:
                slot_name = getattr(slot, "name", None)
                if slot_name:
                    return str(slot_name)
                if isinstance(slot, dict) and slot.get("name"):
                    return str(slot["name"])

        return f"Player {player_id}"

    def _get_item_name(
        self,
        ctx: "BizHawkClientContext",
        item_id: Optional[int],
        player_id: Optional[int],
    ) -> str:
        if item_id is None:
            return "Unknown Item"

        item_names = getattr(ctx, "item_names", None)
        if item_names is not None:
            lookup_in_slot = getattr(item_names, "lookup_in_slot", None)
            if callable(lookup_in_slot) and player_id is not None:
                try:
                    name = lookup_in_slot(item_id, player_id)
                    if name:
                        return str(name)
                except Exception:
                    pass

            lookup_in_game = getattr(item_names, "lookup_in_game", None)
            if callable(lookup_in_game):
                try:
                    name = lookup_in_game(item_id)
                    if name:
                        return str(name)
                except Exception:
                    pass

            get_name = getattr(item_names, "get", None)
            if callable(get_name):
                try:
                    name = get_name(item_id)
                    if name:
                        return str(name)
                except Exception:
                    pass

            try:
                name = item_names[item_id]
                if name:
                    return str(name)
            except Exception:
                pass

        fallback_name = ITEM_ID_TO_NAME.get(item_id)
        if fallback_name:
            return fallback_name

        return f"Item {item_id}"

    def _get_scouted_location_info(self, ctx: "BizHawkClientContext", location_id: int):
        locations_info = getattr(ctx, "locations_info", None)
        if locations_info is None:
            return None

        get_info = getattr(locations_info, "get", None)
        if callable(get_info):
            try:
                info = get_info(location_id)
                if info is not None:
                    return info
            except Exception:
                pass

        try:
            return locations_info[location_id]
        except Exception:
            return None

    def _sanitize_notification_text(
        self,
        text: str,
        max_length: Optional[int] = AP_NOTIFICATION_MAILBOX_TEXT_LENGTH,
        allow_newlines: bool = False,
    ) -> str:
        sanitized_chars: List[str] = []
        for char in str(text):
            codepoint = ord(char)
            if allow_newlines and codepoint == 0x0A:
                sanitized_chars.append(char)
            elif 0x20 <= codepoint <= 0x7E:
                sanitized_chars.append(char)
            else:
                sanitized_chars.append("?")

            if max_length is not None and len(sanitized_chars) >= max_length - 1:
                break

        return "".join(sanitized_chars)

    def _ellipsize_notification_line(self, text: str, max_chars: int) -> str:
        if max_chars <= 0:
            return ""
        if len(text) <= max_chars:
            return text
        if max_chars <= 3:
            return "." * max_chars
        trimmed = text[: max_chars - 3].rstrip()
        if not trimmed:
            trimmed = text[: max_chars - 3]
        return trimmed + "..."

    def _fit_notification_text(
        self,
        text: str,
        mailbox_length: int,
        max_chars_per_line: int,
        max_lines: int,
    ) -> str:
        sanitized = self._sanitize_notification_text(text, None, allow_newlines=True)
        wrapper = textwrap.TextWrapper(
            width=max_chars_per_line,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
            drop_whitespace=True,
        )

        lines: List[str] = []
        overflowed = False

        for paragraph in sanitized.replace("\r", "").split("\n"):
            paragraph = " ".join(paragraph.split())
            wrapped = wrapper.wrap(paragraph) if paragraph else [""]

            for line in wrapped:
                if len(lines) >= max_lines:
                    overflowed = True
                    break
                lines.append(line)

            if overflowed:
                break

        if not lines:
            lines = [""]

        if overflowed:
            lines[max_lines - 1] = self._ellipsize_notification_line(lines[max_lines - 1], max_chars_per_line)

        fitted = "\n".join(lines[:max_lines])
        if len(fitted) >= mailbox_length:
            fitted = fitted[: mailbox_length - 1]
        return fitted

    async def _send_location_checks(
        self,
        ctx: "BizHawkClientContext",
        location_ids: List[int],
    ) -> None:
        if not location_ids:
            return

        scout_locations: List[int] = []
        for location_id in location_ids:
            if location_id not in self.pending_checked_location_notifications:
                self.pending_checked_location_notifications.append(location_id)

            if self._get_scouted_location_info(ctx, location_id) is None:
                scout_locations.append(location_id)

        messages = []
        if scout_locations:
            messages.append({"cmd": "LocationScouts", "locations": scout_locations, "create_as_hint": 0})
        messages.append({"cmd": "LocationChecks", "locations": location_ids})
        await ctx.send_msgs(messages)

    async def _flush_received_notification(
        self,
        ctx: "BizHawkClientContext",
        mailbox_state: int,
    ) -> int:
        if (
            not self.notification_mailbox_initialized
            or mailbox_state != AP_NOTIFICATION_MAILBOX_EMPTY
            or not self.pending_received_notifications
        ):
            return mailbox_state

        message = self.pending_received_notifications[0]
        message_bytes = message.encode("ascii", errors="replace")[:AP_NOTIFICATION_MAILBOX_TEXT_LENGTH - 1]
        payload = (message_bytes + b"\x00").ljust(AP_NOTIFICATION_MAILBOX_TEXT_LENGTH, b"\x00")

        try:
            await bizhawk.write(
                ctx.bizhawk_ctx,
                [
                    (AP_NOTIFICATION_MAILBOX_TEXT_ADDR, payload, "RDRAM"),
                    (AP_NOTIFICATION_MAILBOX_STATE_ADDR, u32_bytes(AP_NOTIFICATION_MAILBOX_QUEUED), "RDRAM"),
                ],
            )
        except bizhawk.RequestFailedError:
            return mailbox_state

        self.pending_received_notifications.pop(0)
        return AP_NOTIFICATION_MAILBOX_QUEUED

    async def _flush_sent_check_notification(
        self,
        ctx: "BizHawkClientContext",
        mailbox_state: int,
    ) -> int:
        if (
            not self.notification_mailbox_initialized
            or mailbox_state != AP_NOTIFICATION_MAILBOX_EMPTY
            or not self.pending_sent_check_notifications
        ):
            return mailbox_state

        message = self.pending_sent_check_notifications[0]
        message_bytes = message.encode("ascii", errors="replace")[:AP_CHECK_NOTIFICATION_MAILBOX_TEXT_LENGTH - 1]
        payload = (message_bytes + b"\x00").ljust(AP_CHECK_NOTIFICATION_MAILBOX_TEXT_LENGTH, b"\x00")

        try:
            await bizhawk.write(
                ctx.bizhawk_ctx,
                [
                    (AP_CHECK_NOTIFICATION_MAILBOX_TEXT_ADDR, payload, "RDRAM"),
                    (AP_CHECK_NOTIFICATION_MAILBOX_STATE_ADDR, u32_bytes(AP_NOTIFICATION_MAILBOX_QUEUED), "RDRAM"),
                ],
            )
        except bizhawk.RequestFailedError:
            return mailbox_state

        self.pending_sent_check_notifications.pop(0)
        return AP_NOTIFICATION_MAILBOX_QUEUED

    async def _apply_pending_deathlink(self, in_active_stage: bool, bond_kia: int) -> None:
        if not self.pending_deathlink or not in_active_stage or bond_kia != 0:
            return

        if not arm_deathlink_trigger():
            return

        self.pending_deathlink = False
        self.awaiting_local_deathlink = True

    async def _send_bond_deathlink(
        self,
        ctx: "BizHawkClientContext",
        mission_info: Optional[dict],
    ) -> None:
        if not is_deathlink_enabled(ctx) or not hasattr(ctx, "send_death"):
            return

        if self.awaiting_local_deathlink:
            self.awaiting_local_deathlink = False
            clear_deathlink_trigger()
            return

        now = time.monotonic()
        if now - self.last_deathlink_send_at < DEATHLINK_SEND_COOLDOWN_SECONDS:
            return

        mission_name = mission_info["name"] if mission_info is not None else "an active mission"
        deathlink_key_before_send = get_deathlink_key(getattr(ctx, "last_death_link", None))
        try:
            await ctx.send_death(f"Bond was killed in action on {mission_name}.")
        except Exception:
            deathlink_key_after_send = get_deathlink_key(getattr(ctx, "last_death_link", None))
            if deathlink_key_after_send is not None and deathlink_key_after_send != deathlink_key_before_send:
                self.last_processed_deathlink_key = deathlink_key_after_send
            return

        deathlink_key_after_send = get_deathlink_key(getattr(ctx, "last_death_link", None))
        if deathlink_key_after_send is not None and deathlink_key_after_send != deathlink_key_before_send:
            self.last_processed_deathlink_key = deathlink_key_after_send
        self.last_deathlink_send_at = now

    # --- Mission clears and objective checks ---
    async def _check_mission_clear(
        self,
        ctx: "BizHawkClientContext",
        mission_info: Optional[dict],
        screen_id: int,
        failed_or_aborted: int,
        bond_kia: int,
        selected_difficulty: int,
    ) -> None:
        raw_flags = await self._read_objective_flags(ctx)
        if (
            mission_info is None
            or raw_flags is None
            or screen_id != SCREEN_MISSION_DEBRIEF
            or failed_or_aborted != 0
            or bond_kia != 0
            or not mission_objectives_complete(
                mission_info["map_id"],
                selected_difficulty + 1,
                raw_flags,
            )
        ):
            self.pending_success_objectives.clear()
            return

        location_ids = await self._collect_success_objective_checks(
            ctx,
            mission_info["map_id"],
            selected_difficulty + 1,
        )

        difficulty_code = selected_difficulty + 1
        location_ids.append(
            get_mission_clear_location_id(
                mission_info,
                difficulty_code,
                get_mission_clear_mode(ctx),
            )
        )
        if mission_info["name"] == "Cradle":
            location_ids.append(STOPPED_GOLDENEYE_ID)

        new_location_ids = [loc for loc in location_ids if loc not in self.local_checked_locations]
        if not new_location_ids:
            return

        self.local_checked_locations.update(new_location_ids)
        await self._send_location_checks(ctx, new_location_ids)

        completion_writes = [
            (COMPLETED_BASE_ADDR + mission_info["ram_offset"], [1], "RDRAM"),
        ]
        try:
            await bizhawk.write(ctx.bizhawk_ctx, completion_writes)
        except bizhawk.RequestFailedError:
            pass

    async def _read_objective_flags(self, ctx: "BizHawkClientContext") -> Optional[bytes]:
        try:
            return (await bizhawk.read(
                ctx.bizhawk_ctx,
                [(OBJECTIVE_FLAG_BASE_ADDR, OBJECTIVE_FLAG_BLOCK_SIZE, "RDRAM")],
            ))[0]
        except bizhawk.RequestFailedError:
            return None

    async def _collect_success_objective_checks(
        self,
        ctx: "BizHawkClientContext",
        map_id: int,
        difficulty_code: int,
    ) -> List[int]:
        objective_mode = get_objective_mode(ctx)
        objective_location_data = get_objective_location_data(ctx)
        raw_flags = await self._read_objective_flags(ctx)

        location_ids: List[int] = []
        if raw_flags is not None:
            previous_flags = self.objective_prev_flags or self.objective_baseline_flags
            for ap_code, data in objective_location_data.items():
                if ap_code in self.local_checked_locations:
                    continue
                if data["map_id"] != map_id:
                    continue
                if not objective_matches_difficulty(objective_mode, data["difficulty_code"], difficulty_code):
                    continue
                if not data["requires_success"]:
                    continue
                offset = data["offset"] * 4
                if ap_code in self.pending_success_objectives or objective_became_complete(
                    previous_flags, raw_flags, offset
                ):
                    location_ids.append(ap_code)
                    self.pending_success_objectives.discard(ap_code)

        if self.pending_success_objectives:
            for ap_code in sorted(self.pending_success_objectives):
                if ap_code not in location_ids and ap_code not in self.local_checked_locations:
                    location_ids.append(ap_code)
            self.pending_success_objectives.clear()

        return location_ids

    async def _snapshot_objectives(
        self,
        ctx: "BizHawkClientContext",
        map_id: int,
        difficulty_code: int,
    ) -> None:
        objective_mode = get_objective_mode(ctx)
        objective_location_data = get_objective_location_data(ctx)
        raw_flags = await self._read_objective_flags(ctx)
        if raw_flags is None:
            return

        previous_flags = self.objective_prev_flags or self.objective_baseline_flags
        new_checks: List[int] = []
        for ap_code, data in objective_location_data.items():
            if ap_code in self.local_checked_locations:
                continue
            if data["map_id"] != map_id:
                continue
            if not objective_matches_difficulty(objective_mode, data["difficulty_code"], difficulty_code):
                continue
            offset = data["offset"] * 4
            if not objective_became_complete(previous_flags, raw_flags, offset):
                continue
            if data["requires_success"]:
                self.pending_success_objectives.add(ap_code)
            else:
                self.local_checked_locations.add(ap_code)
                new_checks.append(ap_code)

        self.objective_prev_flags = raw_flags

        if new_checks:
            await self._send_location_checks(ctx, new_checks)

    async def _check_objectives(
        self,
        ctx: "BizHawkClientContext",
        mission_info: dict,
        selected_difficulty: int,
    ) -> None:
        raw_flags = await self._read_objective_flags(ctx)
        if raw_flags is None:
            return

        current_difficulty_code = selected_difficulty + 1
        if self.objective_baseline_flags is None:
            self.objective_baseline_flags = raw_flags
            self.objective_prev_flags = raw_flags
            return

        current_map_id = mission_info["map_id"]
        objective_mode = get_objective_mode(ctx)
        objective_location_data = get_objective_location_data(ctx)
        new_checks = []
        for ap_code, data in objective_location_data.items():
            if data["map_id"] != current_map_id or ap_code in self.local_checked_locations:
                continue
            if not objective_matches_difficulty(objective_mode, data["difficulty_code"], current_difficulty_code):
                continue
            offset = data["offset"] * 4
            if offset < 0 or offset + 4 > len(raw_flags):
                continue
            prev_value = read_objective_status(self.objective_prev_flags, offset)
            current_value = read_objective_status(raw_flags, offset)
            if prev_value != 1 and current_value == 1:
                if data["requires_success"]:
                    self.pending_success_objectives.add(ap_code)
                else:
                    self.local_checked_locations.add(ap_code)
                    new_checks.append(ap_code)

        self.objective_prev_flags = raw_flags

        if new_checks:
            await self._send_location_checks(ctx, new_checks)

    # --- Live item effects and loadout ---
    async def _apply_incremental_items(
        self,
        ctx: "BizHawkClientContext",
        bonddata_ptr: int,
        received_counts: Dict[int, int],
        in_active_stage: bool,
        loadout_pending: bool,
    ) -> List[tuple]:
        writes: List[tuple] = []
        pending_effect_defs = {
            item_id: effect_def
            for item_id, effect_def in ITEM_EFFECT_DEFS.items()
            if received_counts.get(item_id, 0) > self.effect_items_applied.get(item_id, 0)
        }
        if not pending_effect_defs:
            return writes

        ammo_offsets: Set[int] = set()
        for effect_def in pending_effect_defs.values():
            effect_type = effect_def.get("effect_type")
            if effect_type in {"ammo", "weapon"} and "ammo_offset" in effect_def:
                ammo_offsets.add(effect_def["ammo_offset"])
            elif effect_type == "multi_ammo":
                for ammo_target in effect_def.get("ammo_targets", []):
                    if "ammo_offset" in ammo_target:
                        ammo_offsets.add(ammo_target["ammo_offset"])

        ammo_values: Dict[int, int] = {}
        if ammo_offsets:
            ammo_reads = await bizhawk.read(
                ctx.bizhawk_ctx,
                [(bonddata_ptr + offset, 4, "RDRAM") for offset in sorted(ammo_offsets)],
            )
            ammo_values = {
                offset: int.from_bytes(ammo_reads[idx], "big")
                for idx, offset in enumerate(sorted(ammo_offsets))
            }

        inventory_weapon_ids: List[int] = []
        for item_id, effect_def in pending_effect_defs.items():
            received_count = received_counts.get(item_id, 0)
            applied_count = self.effect_items_applied.get(item_id, 0)
            delta = received_count - applied_count
            effect_type = effect_def.get("effect_type")

            if effect_type == "multi_ammo":
                for ammo_target in effect_def.get("ammo_targets", []):
                    ammo_offset = ammo_target.get("ammo_offset")
                    ammo_grant = ammo_target.get("ammo_grant")
                    ammo_max = ammo_target.get("ammo_max")
                    if ammo_offset is None or ammo_grant is None or ammo_max is None:
                        continue
                    ammo_values[ammo_offset] = min(
                        ammo_values.get(ammo_offset, 0) + (ammo_grant * delta),
                        ammo_max,
                    )
            elif effect_type in {"ammo", "weapon"}:
                ammo_offset = effect_def.get("ammo_offset")
                ammo_grant = effect_def.get("ammo_grant")
                ammo_max = effect_def.get("ammo_max")
                if ammo_offset is not None and ammo_grant is not None and ammo_max is not None:
                    ammo_values[ammo_offset] = min(
                        ammo_values.get(ammo_offset, 0) + (ammo_grant * delta),
                        ammo_max,
                    )
                if effect_type == "weapon" and applied_count <= 0:
                    inventory_weapon_ids.append(effect_def["weapon_id"])
                    for extra_weapon_id in effect_def.get("extra_inventory_ids", []):
                        inventory_weapon_ids.append(extra_weapon_id)
            elif effect_type == "health_full":
                writes.extend(self._build_full_health_writes(bonddata_ptr))
            elif effect_type == "armor_full":
                writes.extend(self._build_full_armor_writes(bonddata_ptr))
            elif effect_type == "enemy_rockets_trap":
                writes.append((CHEAT_ENEMY_ROCKETS_ADDR, [1], "RDRAM"))
            elif effect_type == "goldeneye_trap":
                if not in_active_stage:
                    continue
                writes.append((GOLDENEYE_TRAP_ADDR, [1], "RDRAM"))
            elif effect_type == "holster_gun_trap":
                if not in_active_stage:
                    continue
                writes.extend(self._build_clear_hand_writes(bonddata_ptr, GUNRIGHT))
                writes.extend(self._build_clear_hand_writes(bonddata_ptr, GUNLEFT))

            self.effect_items_applied[item_id] = received_count

        for ammo_offset, ammo_value in ammo_values.items():
            writes.append((bonddata_ptr + ammo_offset, u32_bytes(ammo_value), "RDRAM"))

        if in_active_stage and not loadout_pending and inventory_weapon_ids:
            writes.extend(await self._add_inventory_items(ctx, bonddata_ptr, inventory_weapon_ids))

        return writes

    def _build_full_health_writes(self, bonddata_ptr: int) -> List[tuple]:
        return [
            (bonddata_ptr + HEALTH_DISPLAY_OFFSET, FULL_FLOAT_BYTES, "RDRAM"),
            (bonddata_ptr + HEALTH_ACTUAL_OFFSET, FULL_FLOAT_BYTES, "RDRAM"),
        ]

    def _build_full_armor_writes(self, bonddata_ptr: int) -> List[tuple]:
        return [
            (bonddata_ptr + ARMOR_DISPLAY_OFFSET, FULL_FLOAT_BYTES, "RDRAM"),
            (bonddata_ptr + ARMOR_ACTUAL_OFFSET, FULL_FLOAT_BYTES, "RDRAM"),
        ]

    async def _try_apply_owned_loadout(
        self,
        ctx: "BizHawkClientContext",
        bonddata_ptr: int,
        received_counts: Dict[int, int],
        mission_info: dict,
    ) -> bool:
        # Match the last working build's startup timing:
        # wait for the first right-hand draw request, then hold the slapper
        # weapon field briefly while we rebuild the mission-start inventory.
        hand_next_addr = bonddata_ptr + OFF_HANDS_BASE + HAND_OFF_NEXT_WEAPON
        try:
            hand_next = int.from_bytes(
                (await bizhawk.read(ctx.bizhawk_ctx, [(hand_next_addr, 4, "RDRAM")]))[0],
                "big",
            )
        except bizhawk.RequestFailedError:
            return False

        if self.pending_loadout_hold_frames == 0:
            if not (hand_next != 0 and self.pending_loadout_last_hand_next == 0):
                self.pending_loadout_last_hand_next = hand_next
                return False
            self.pending_loadout_hold_frames = LOADOUT_TRIGGER_HOLD_FRAMES

        self.pending_loadout_last_hand_next = hand_next

        try:
            loadout_reads = await bizhawk.read(
                ctx.bizhawk_ctx,
                [
                    (bonddata_ptr + OFF_INV_HEAD, 4, "RDRAM"),
                    (bonddata_ptr + OFF_INV_POOL, 4, "RDRAM"),
                    (bonddata_ptr + OFF_INV_MAX, 4, "RDRAM"),
                ],
            )
        except bizhawk.RequestFailedError:
            return False

        head_ptr = int.from_bytes(loadout_reads[0], "big") - 0x80000000
        pool_ptr = int.from_bytes(loadout_reads[1], "big") - 0x80000000
        max_items = int.from_bytes(loadout_reads[2], "big")

        if pool_ptr <= 0 or max_items <= 0:
            return False

        try:
            pool_bytes = (await bizhawk.read(
                ctx.bizhawk_ctx,
                [(pool_ptr, max_items * INV_ITEM_SIZE, "RDRAM")],
            ))[0]
        except bizhawk.RequestFailedError:
            return False

        preserved_entries = self._get_preserved_inventory_entries(
            head_ptr,
            pool_ptr,
            pool_bytes,
            mission_info["name"],
        )
        inventory_entries = [{"type": INV_ITEM_WEAPON, "weapon_id": ITEM_FIST, "left_weapon_id": 0}]
        ammo_targets: Dict[int, int] = {}
        seen_weapon_ids = {ITEM_UNARMED, ITEM_FIST}

        for item_id, effect_def in ITEM_EFFECT_DEFS.items():
            received_count = received_counts.get(item_id, 0)
            if received_count <= 0:
                continue

            effect_type = effect_def.get("effect_type")
            if effect_type == "weapon":
                weapon_id = effect_def["weapon_id"]
                if weapon_id not in seen_weapon_ids:
                    inventory_entries.append({
                        "type": INV_ITEM_WEAPON,
                        "weapon_id": weapon_id,
                        "left_weapon_id": 0,
                    })
                    seen_weapon_ids.add(weapon_id)
                for extra_weapon_id in effect_def.get("extra_inventory_ids", []):
                    if extra_weapon_id not in seen_weapon_ids:
                        inventory_entries.append({
                            "type": INV_ITEM_WEAPON,
                            "weapon_id": extra_weapon_id,
                            "left_weapon_id": 0,
                        })
                        seen_weapon_ids.add(extra_weapon_id)

            if effect_type == "multi_ammo":
                for ammo_target in effect_def.get("ammo_targets", []):
                    ammo_offset = ammo_target.get("ammo_offset")
                    ammo_grant = ammo_target.get("ammo_grant")
                    ammo_max = ammo_target.get("ammo_max")
                    if ammo_offset is None or ammo_grant is None or ammo_max is None:
                        continue
                    ammo_targets[ammo_offset] = min(
                        ammo_targets.get(ammo_offset, 0) + (ammo_grant * received_count),
                        ammo_max,
                    )
            elif effect_type in {"ammo", "weapon"}:
                ammo_offset = effect_def.get("ammo_offset")
                ammo_grant = effect_def.get("ammo_grant")
                ammo_max = effect_def.get("ammo_max")
                if ammo_offset is not None and ammo_grant is not None and ammo_max is not None:
                    ammo_targets[ammo_offset] = min(
                        ammo_targets.get(ammo_offset, 0) + (ammo_grant * received_count),
                        ammo_max,
                    )

            self.effect_items_applied[item_id] = received_count

        for entry in preserved_entries:
            weapon_id = entry["weapon_id"]
            if weapon_id in seen_weapon_ids:
                continue
            inventory_entries.append({
                "type": entry["type"],
                "weapon_id": weapon_id,
                "left_weapon_id": entry.get("left_weapon_id", 0),
            })
            seen_weapon_ids.add(weapon_id)

        if len(inventory_entries) > max_items:
            inventory_entries = inventory_entries[:max_items]
            logger.warning(
                "Mission %s loadout truncated to %d inventory slots",
                mission_info["name"],
                max_items,
            )

        fist_slot_index = next(
            (index for index, entry in enumerate(inventory_entries) if entry["weapon_id"] == ITEM_FIST),
            0,
        )
        equipped_slot_index = fist_slot_index

        writes = self._build_inventory_rebuild_writes(
            bonddata_ptr,
            pool_ptr,
            max_items,
            inventory_entries,
            equipped_slot_index,
        )

        writes.append((
            bonddata_ptr + OFF_HANDS_BASE + HAND_OFF_WEAPONNUM,
            u32_bytes(ITEM_FIST),
            "RDRAM",
        ))

        for ammo_offset, amount in ammo_targets.items():
            writes.append((bonddata_ptr + ammo_offset, u32_bytes(amount), "RDRAM"))

        try:
            await bizhawk.write(ctx.bizhawk_ctx, writes)
        except bizhawk.RequestFailedError:
            return False

        self.pending_loadout_hold_frames -= 1
        if self.pending_loadout_hold_frames <= 0:
            return True
        return False

    # --- Inventory helpers ---
    def _build_inventory_rebuild_writes(
        self,
        bonddata_ptr: int,
        pool_ptr: int,
        max_items: int,
        inventory_entries: List[Dict[str, int]],
        equipped_slot_index: int = 0,
    ) -> List[tuple]:
        writes: List[tuple] = []
        for index in range(max_items):
            entry = pool_ptr + index * INV_ITEM_SIZE
            if index < len(inventory_entries):
                next_entry = pool_ptr + ((index + 1) % len(inventory_entries)) * INV_ITEM_SIZE
                prev_entry = pool_ptr + ((index - 1 + len(inventory_entries)) % len(inventory_entries)) * INV_ITEM_SIZE
                current_entry = inventory_entries[index]
                writes.extend([
                    (entry + 0x00, s32_bytes(current_entry["type"]), "RDRAM"),
                    (entry + 0x04, u32_bytes(current_entry["weapon_id"]), "RDRAM"),
                    (entry + 0x08, u32_bytes(current_entry.get("left_weapon_id", 0)), "RDRAM"),
                    (entry + 0x0C, ptr_bytes(next_entry), "RDRAM"),
                    (entry + 0x10, ptr_bytes(prev_entry), "RDRAM"),
                ])
            else:
                writes.extend([
                    (entry + 0x00, s32_bytes(INV_ITEM_NONE), "RDRAM"),
                    (entry + 0x04, u32_bytes(0), "RDRAM"),
                    (entry + 0x08, u32_bytes(0), "RDRAM"),
                    (entry + 0x0C, ptr_bytes(0), "RDRAM"),
                    (entry + 0x10, ptr_bytes(0), "RDRAM"),
                ])

        head_ptr = pool_ptr if inventory_entries else 0
        writes.extend([
            (bonddata_ptr + OFF_INV_HEAD, ptr_bytes(head_ptr), "RDRAM"),
            (bonddata_ptr + OFF_ALL_GUNS, u32_bytes(0), "RDRAM"),
            (bonddata_ptr + OFF_EQUIP_CUR, u32_bytes(equipped_slot_index), "RDRAM"),
        ])

        return writes

    async def _add_inventory_item(
        self,
        ctx: "BizHawkClientContext",
        bonddata_ptr: int,
        weapon_id: int,
    ) -> List[tuple]:
        try:
            inv_reads = await bizhawk.read(
                ctx.bizhawk_ctx,
                [
                    (bonddata_ptr + OFF_INV_HEAD, 4, "RDRAM"),
                    (bonddata_ptr + OFF_INV_POOL, 4, "RDRAM"),
                    (bonddata_ptr + OFF_INV_MAX, 4, "RDRAM"),
                ],
            )
        except bizhawk.RequestFailedError:
            return []

        head_ptr = int.from_bytes(inv_reads[0], "big") - 0x80000000
        pool_ptr = int.from_bytes(inv_reads[1], "big") - 0x80000000
        max_items = int.from_bytes(inv_reads[2], "big")
        if pool_ptr <= 0 or max_items <= 0:
            return []

        try:
            pool_bytes = (await bizhawk.read(
                ctx.bizhawk_ctx,
                [(pool_ptr, max_items * INV_ITEM_SIZE, "RDRAM")],
            ))[0]
        except bizhawk.RequestFailedError:
            return []

        free_index: Optional[int] = None
        current = head_ptr
        seen: Set[int] = set()
        while current > 0 and current not in seen:
            seen.add(current)
            rel = current - pool_ptr
            if rel < 0 or rel + INV_ITEM_SIZE > len(pool_bytes):
                break
            entry_type = int.from_bytes(pool_bytes[rel:rel + 4], "big", signed=True)
            current_weapon = int.from_bytes(pool_bytes[rel + 4:rel + 8], "big")
            if entry_type == INV_ITEM_WEAPON and current_weapon == weapon_id:
                return []
            next_ptr = int.from_bytes(pool_bytes[rel + 0x0C:rel + 0x10], "big") - 0x80000000
            current = next_ptr

        for index in range(max_items):
            rel = index * INV_ITEM_SIZE
            entry_type = int.from_bytes(pool_bytes[rel:rel + 4], "big", signed=True)
            if entry_type == INV_ITEM_NONE:
                free_index = index
                break

        if free_index is None:
            logger.warning("No free inventory slot for weapon id %d", weapon_id)
            return []

        slot_ptr = pool_ptr + free_index * INV_ITEM_SIZE
        writes = [
            (slot_ptr + 0x00, s32_bytes(INV_ITEM_WEAPON), "RDRAM"),
            (slot_ptr + 0x04, u32_bytes(weapon_id), "RDRAM"),
            (slot_ptr + 0x08, u32_bytes(0), "RDRAM"),
        ]

        if head_ptr <= 0:
            writes.extend([
                (slot_ptr + 0x0C, ptr_bytes(slot_ptr), "RDRAM"),
                (slot_ptr + 0x10, ptr_bytes(slot_ptr), "RDRAM"),
                (bonddata_ptr + OFF_INV_HEAD, ptr_bytes(slot_ptr), "RDRAM"),
                (bonddata_ptr + OFF_EQUIP_CUR, u32_bytes(0), "RDRAM"),
            ])
            return writes

        head_rel = head_ptr - pool_ptr
        if head_rel < 0 or head_rel + INV_ITEM_SIZE > len(pool_bytes):
            return []

        tail_ptr = int.from_bytes(pool_bytes[head_rel + 0x10:head_rel + 0x14], "big") - 0x80000000
        if tail_ptr <= 0:
            tail_ptr = head_ptr

        writes.extend([
            (slot_ptr + 0x0C, ptr_bytes(head_ptr), "RDRAM"),
            (slot_ptr + 0x10, ptr_bytes(tail_ptr), "RDRAM"),
            (tail_ptr + 0x0C, ptr_bytes(slot_ptr), "RDRAM"),
            (head_ptr + 0x10, ptr_bytes(slot_ptr), "RDRAM"),
        ])
        return writes

    async def _add_inventory_items(
        self,
        ctx: "BizHawkClientContext",
        bonddata_ptr: int,
        weapon_ids: List[int],
    ) -> List[tuple]:
        if not weapon_ids:
            return []

        try:
            inv_reads = await bizhawk.read(
                ctx.bizhawk_ctx,
                [
                    (bonddata_ptr + OFF_INV_HEAD, 4, "RDRAM"),
                    (bonddata_ptr + OFF_INV_POOL, 4, "RDRAM"),
                    (bonddata_ptr + OFF_INV_MAX, 4, "RDRAM"),
                ],
            )
        except bizhawk.RequestFailedError:
            return []

        head_ptr = int.from_bytes(inv_reads[0], "big") - 0x80000000
        pool_ptr = int.from_bytes(inv_reads[1], "big") - 0x80000000
        max_items = int.from_bytes(inv_reads[2], "big")
        if pool_ptr <= 0 or max_items <= 0:
            return []

        try:
            pool_bytes = (await bizhawk.read(
                ctx.bizhawk_ctx,
                [(pool_ptr, max_items * INV_ITEM_SIZE, "RDRAM")],
            ))[0]
        except bizhawk.RequestFailedError:
            return []

        existing_weapon_ids: Set[int] = set()
        current = head_ptr
        seen_ptrs: Set[int] = set()
        while current > 0 and current not in seen_ptrs:
            seen_ptrs.add(current)
            rel = current - pool_ptr
            if rel < 0 or rel + INV_ITEM_SIZE > len(pool_bytes):
                break
            entry_type = int.from_bytes(pool_bytes[rel:rel + 4], "big", signed=True)
            if entry_type == INV_ITEM_WEAPON:
                existing_weapon_ids.add(int.from_bytes(pool_bytes[rel + 4:rel + 8], "big"))
            current = int.from_bytes(pool_bytes[rel + 0x0C:rel + 0x10], "big") - 0x80000000

        free_slot_indices = [
            index
            for index in range(max_items)
            if int.from_bytes(
                pool_bytes[index * INV_ITEM_SIZE:(index * INV_ITEM_SIZE) + 4],
                "big",
                signed=True,
            ) == INV_ITEM_NONE
        ]

        current_head_ptr = head_ptr
        current_tail_ptr = 0
        if current_head_ptr > 0:
            head_rel = current_head_ptr - pool_ptr
            if 0 <= head_rel and head_rel + INV_ITEM_SIZE <= len(pool_bytes):
                current_tail_ptr = int.from_bytes(
                    pool_bytes[head_rel + 0x10:head_rel + 0x14],
                    "big",
                ) - 0x80000000
        writes: List[tuple] = []

        for weapon_id in weapon_ids:
            if weapon_id in existing_weapon_ids:
                continue
            if not free_slot_indices:
                logger.warning("No free inventory slot for weapon id %d", weapon_id)
                break

            slot_index = free_slot_indices.pop(0)
            slot_ptr = pool_ptr + slot_index * INV_ITEM_SIZE
            writes.extend([
                (slot_ptr + 0x00, s32_bytes(INV_ITEM_WEAPON), "RDRAM"),
                (slot_ptr + 0x04, u32_bytes(weapon_id), "RDRAM"),
                (slot_ptr + 0x08, u32_bytes(0), "RDRAM"),
            ])

            if current_head_ptr <= 0:
                writes.extend([
                    (slot_ptr + 0x0C, ptr_bytes(slot_ptr), "RDRAM"),
                    (slot_ptr + 0x10, ptr_bytes(slot_ptr), "RDRAM"),
                    (bonddata_ptr + OFF_INV_HEAD, ptr_bytes(slot_ptr), "RDRAM"),
                    (bonddata_ptr + OFF_EQUIP_CUR, u32_bytes(0), "RDRAM"),
                ])
                current_head_ptr = slot_ptr
                current_tail_ptr = slot_ptr
            else:
                if current_tail_ptr <= 0:
                    current_tail_ptr = current_head_ptr
                writes.extend([
                    (slot_ptr + 0x0C, ptr_bytes(current_head_ptr), "RDRAM"),
                    (slot_ptr + 0x10, ptr_bytes(current_tail_ptr), "RDRAM"),
                    (current_tail_ptr + 0x0C, ptr_bytes(slot_ptr), "RDRAM"),
                    (current_head_ptr + 0x10, ptr_bytes(slot_ptr), "RDRAM"),
                ])
                current_tail_ptr = slot_ptr

            existing_weapon_ids.add(weapon_id)

        return writes

    def _build_clear_hand_writes(
        self,
        bonddata_ptr: int,
        hand: int,
        current_weapon: int = ITEM_UNARMED,
        next_weapon: int = ITEM_UNARMED,
    ) -> List[tuple]:
        # Keep trap hand clears small: just clear the live weapon ids.
        hand_base = bonddata_ptr + OFF_HANDS_BASE + hand * HAND_SIZE

        writes = [
            (hand_base + HAND_OFF_PREVIOUS_WEAPON, u32_bytes(current_weapon), "RDRAM"),
            (hand_base + HAND_OFF_WEAPONNUM, u32_bytes(current_weapon), "RDRAM"),
            (hand_base + HAND_OFF_NEXT_WEAPON, u32_bytes(next_weapon), "RDRAM"),
            (bonddata_ptr + OFF_HAND_ITEM + hand * 4, u32_bytes(current_weapon), "RDRAM"),
        ]
        return writes

    def _get_preserved_inventory_entries(
        self,
        head_ptr: int,
        pool_ptr: int,
        pool_bytes: bytes,
        mission_name: str = "",
    ) -> List[Dict[str, int]]:
        if head_ptr <= 0 or pool_ptr <= 0:
            return []

        entries: List[Dict[str, int]] = []
        current = head_ptr
        seen_ptrs: Set[int] = set()
        allowed_weapon_ids = MISSION_STARTUP_PRESERVE_WEAPON_IDS.get(mission_name, set())

        while current > 0 and current not in seen_ptrs:
            seen_ptrs.add(current)
            rel = current - pool_ptr
            if rel < 0 or rel + INV_ITEM_SIZE > len(pool_bytes):
                break

            entry_type = int.from_bytes(pool_bytes[rel:rel + 4], "big", signed=True)
            weapon_id = int.from_bytes(pool_bytes[rel + 4:rel + 8], "big")
            left_weapon_id = int.from_bytes(pool_bytes[rel + 8:rel + 12], "big")
            next_ptr = int.from_bytes(pool_bytes[rel + 0x0C:rel + 0x10], "big") - 0x80000000

            should_keep = entry_type != INV_ITEM_NONE and (
                weapon_id not in AP_CONTROLLED_WEAPON_IDS
                or weapon_id == ITEM_FIST
                or weapon_id in allowed_weapon_ids
            )
            if should_keep:
                entries.append({
                    "type": entry_type,
                    "weapon_id": weapon_id,
                    "left_weapon_id": left_weapon_id,
                })

            current = next_ptr

        return entries

    # --- Goal completion ---
    async def _check_goal(self, ctx: "BizHawkClientContext") -> None:
        if ctx.finished_game:
            return

        goal = get_option_value(ctx, "goal", 0)
        if goal == 0:
            if STOPPED_GOLDENEYE_ID in self.local_checked_locations:
                ctx.finished_game = True
        elif goal == 1:
            mission_clear_mode = get_mission_clear_mode(ctx)
            enabled_missions = [
                mission
                for mission in MISSIONS
                if is_enabled_mission(ctx, mission["name"])
            ]
            if mission_clear_mode == MISSION_CLEAR_MODE_PER_MAP:
                all_missions_cleared = all(
                    get_mission_clear_location_id(
                        mission,
                        0,
                        mission_clear_mode,
                    ) in self.local_checked_locations
                    for mission in enabled_missions
                )
            else:
                all_missions_cleared = all(
                    any(
                        clear_location_id in self.local_checked_locations
                        for clear_location_id in get_all_goal_clear_location_ids(mission)
                    )
                    for mission in enabled_missions
                )
            if all_missions_cleared:
                ctx.finished_game = True

        if ctx.finished_game:
            await ctx.send_msgs([{
                "cmd": "StatusUpdate",
                "status": ClientStatus.CLIENT_GOAL,
            }])
