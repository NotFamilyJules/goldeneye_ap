from BaseClasses import Item, Tutorial
from worlds.AutoWorld import WebWorld, World

# Framework exception:
# Archipelago expects this package file to wire together the BizHawk client
# import, the option field list, and the small WebWorld/World entry classes.
# We keep that framework-specific glue here so the rest of the package can stay
# simpler.
# This is safe because it only connects pieces that already live in this
# package and does not add gameplay logic of its own.
from .GoldeneyeClient import GoldeneyeClient
from .Items import MISSION_UNLOCK_NAMES, create_item, create_itempool, item_table
from .Locations import get_location_names, get_total_locations
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
        self.multiworld.push_precollected(
            self.create_item(MISSION_UNLOCK_NAMES[self.options.starting_mission.value - 1])
        )

    def create_regions(self) -> None:
        create_regions(self)

    def set_rules(self) -> None:
        set_rules(self)

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
        return slot_data
