from BaseClasses import Item, Tutorial
from worlds.AutoWorld import WebWorld, World

from .GoldeneyeClient import GoldeneyeClient  # Registers the BizHawk client.
from .Items import MISSION_UNLOCK_NAMES, create_item, create_itempool, item_table
from .Locations import get_location_names, get_total_locations
from .Options import GoldeneyeOptions, create_option_groups
from .Regions import create_regions
from .Rules import set_rules


class GoldeneyeWeb(WebWorld):
    theme = "Party"
    tutorials = [Tutorial(
        "Multiworld Setup Guide",
        "A guide to setting up GoldenEye 007 for Archipelago. "
        "This guide covers single-player, multiworld, and related software.",
        "English",
        "setup_en.md",
        "setup/en",
        ["FamilyJules"],
    )]


class GoldeneyeWorld(World):
    game = "GoldenEye 007"
    item_name_to_id = {name: data.ap_code for name, data in item_table.items() if data.ap_code is not None}
    location_name_to_id = get_location_names()
    options_dataclass = GoldeneyeOptions
    options = GoldeneyeOptions
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
        return {
            "options": {
                option_name: getattr(self.options, option_name).value
                for option_name in (
                    "goal",
                    "starting_mission",
                    "extra_locations",
                    "progressive_weapons",
                    "objective_mode",
                    "mission_clear_mode",
                    "death_link",
                    "trap_chance",
                    "enemy_rockets_trap",
                    "holster_gun_trap",
                )
                if hasattr(self.options, option_name)
            },
            "Seed": self.multiworld.seed_name,
            "Slot": self.multiworld.player_name[self.player],
            "TotalLocations": get_total_locations(self),
        }
