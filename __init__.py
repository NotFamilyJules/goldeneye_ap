import logging

from BaseClasses import CollectionState, Item, Tutorial
from worlds.AutoWorld import WebWorld, World
from worlds.generic.Rules import add_rule

# Framework exception:
# Archipelago expects this package file to wire together the BizHawk client
# import, the option field list, and the small WebWorld/World entry classes.
# We keep that framework-specific glue here so the rest of the package can stay
# simpler.
# This is safe because it only connects pieces that already live in this
# package and does not add gameplay logic of its own.
from .GoldeneyeClient import GoldeneyeClient
from .Items import MISSION_UNLOCK_NAMES, create_item, create_itempool, create_junk_items, item_table
from .Locations import get_location_names, get_total_locations, is_enabled_extra_region
from .Options import GoldeneyeOptions, create_option_groups
from .Regions import create_regions
from .Rules import set_rules


def build_item_name_to_id() -> dict[str, int]:
    item_ids: dict[str, int] = {}
    for name, data in item_table.items():
        if data.ap_code is not None:
            item_ids[name] = data.ap_code
    return item_ids


def build_slot_options(world: "GoldeneyeWorld") -> dict[str, object]:
    option_values: dict[str, object] = {}
    option_names = getattr(world.options_dataclass, "__annotations__", {})
    for option_name in option_names:
        if hasattr(world.options, option_name):
            option_values[option_name] = getattr(world.options, option_name).value
    return option_values


class GoldeneyeWeb(WebWorld):
    theme = "Party"
    tutorials = [
        Tutorial(
            "Multiworld Setup Guide",
            "A guide to setting up GoldenEye 007 for Archipelago. "
            "This guide covers single-player, multiworld, and related software.",
            "English",
            "setup_en.md",
            "setup/en",
            ["FamilyJules"],
        )
    ]


class GoldeneyeWorld(World):
    game = "GoldenEye 007"
    item_name_to_id = build_item_name_to_id()
    location_name_to_id = get_location_names()
    options_dataclass = GoldeneyeOptions
    option_groups = create_option_groups()
    web = GoldeneyeWeb()

    def generate_early(self) -> None:
        # 1. Choose an enabled start; check its access after rules are installed.
        self.random_start = self.options.starting_mission.value == self.options.starting_mission.random_value
        if self.random_start:
            eligible_missions = [
                mission_id
                for mission_id, mission_name in enumerate(MISSION_UNLOCK_NAMES, start=1)
                if is_enabled_extra_region(self, mission_name)
            ]
            self.options.starting_mission.value = self.random.choice(eligible_missions)

        # 2. Give the resolved mission its normal starting unlock.
        self.starting_unlock = self.create_item(MISSION_UNLOCK_NAMES[self.options.starting_mission.value - 1])
        self.multiworld.push_precollected(self.starting_unlock)

    def create_regions(self) -> None:
        create_regions(self)

    def set_rules(self) -> None:
        set_rules(self)
        if self.options.goal.value == 1:
            # Each enabled mission contributes one supported difficulty route.
            clear_groups = [[location for location in self.multiworld.get_locations(self.player)
                             if location.parent_region.name == mission_name and location.name.endswith("(Clear)")]
                            for mission_name in MISSION_UNLOCK_NAMES
                            if is_enabled_extra_region(self, mission_name)]
            add_rule(self.multiworld.get_location("Stopped Goldeneye", self.player),
                     lambda state: all(any(location.can_reach(state) for location in group)
                                       for group in clear_groups))
        self.resolve_starting_mission()

    def resolve_starting_mission(self) -> None:
        # 1. Test actual starting inventory and enabled, non-excluded checks.
        initial_mission = self.options.starting_mission.value
        remaining = [mission_id for mission_id, name in enumerate(MISSION_UNLOCK_NAMES, start=1)
                     if mission_id != initial_mission and is_enabled_extra_region(self, name)]
        locations = [location for location in self.multiworld.get_unfilled_locations(self.player)
                     if location.name not in self.options.exclude_locations.value]
        progression = [item for item in self.multiworld.itempool if item.advancement and item.player == self.player]
        starting_state = CollectionState(self.multiworld)
        starting_state.remove(self.starting_unlock)
        mission_id = initial_mission
        while True:
            mission_name = MISSION_UNLOCK_NAMES[mission_id - 1]
            candidate_unlock = self.create_item(mission_name)
            candidate_state = starting_state.copy()
            candidate_state.collect(candidate_unlock, True)
            reachable = [location for location in locations if location.can_reach(candidate_state)
                         and any(location.can_fill(candidate_state, item) for item in progression)]
            if is_enabled_extra_region(self, mission_name) and reachable:
                break
            # 2. Never retry a rejected mission or reroll the placement seed.
            if not remaining:
                raise ValueError("GoldenEye: no enabled starting mission has a reachable progression check.")
            mission_id = self.random.choice(remaining)
            remaining.remove(mission_id)

        # 3. Exchange only the normal starting unlock, keeping pool size unchanged.
        if mission_id != initial_mission:
            pool_unlock = next(item for item in self.multiworld.itempool
                               if item.player == self.player and item.name == mission_name)
            replacement = (self.starting_unlock if is_enabled_extra_region(self, self.starting_unlock.name)
                           else create_junk_items(self, 1)[0])
            self.multiworld.itempool[self.multiworld.itempool.index(pool_unlock)] = replacement
            self.multiworld.precollected_items[self.player].remove(self.starting_unlock)
            self.multiworld.state.remove(self.starting_unlock)
            self.multiworld.push_precollected(pool_unlock)
            self.options.starting_mission.value = mission_id
            if not self.random_start:
                reason = ("no reachable progression checks" if is_enabled_extra_region(self, self.starting_unlock.name)
                          else "mission disabled by extra_locations")
                logging.warning("GoldenEye player %s: explicit start %s is unavailable (%s); "
                                "randomly selected %s instead (%s reachable progression checks).",
                                self.player, self.starting_unlock.name, reason, mission_name, len(reachable))
            self.starting_unlock = pool_unlock

    def create_items(self) -> None:
        self.multiworld.itempool.extend(create_itempool(self))

    def create_item(self, name: str) -> Item:
        return create_item(self, name)

    def get_filler_item_name(self) -> str:
        return "Ammo Cache"

    def fill_slot_data(self) -> dict[str, object]:
        slot_data = {}
        slot_data["options"] = build_slot_options(self)
        slot_data["Seed"] = self.multiworld.seed_name
        slot_data["Slot"] = self.multiworld.player_name[self.player]
        slot_data["TotalLocations"] = get_total_locations(self)
        # 1. Publish the actual goal checks selected for this generated world.
        goal_missions = MISSION_UNLOCK_NAMES if self.options.goal.value == 1 else ["Cradle"]
        slot_data["goal_clear_groups"] = []
        for mission_name in goal_missions:
            clear_ids = [location.address for location in self.multiworld.get_locations(self.player)
                         if location.parent_region.name == mission_name and location.name.endswith("(Clear)")]
            if clear_ids:
                slot_data["goal_clear_groups"].append(clear_ids)
        slot_data["goal_location_id"] = self.location_name_to_id["Stopped Goldeneye"]
        return slot_data
