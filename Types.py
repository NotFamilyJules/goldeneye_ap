from typing import NamedTuple, Optional
from BaseClasses import Location, Item, ItemClassification


class GoldeneyeLocation(Location):
    game = "GoldenEye 007"


class GoldeneyeItem(Item):
    game = "GoldenEye 007"


class ItemData(NamedTuple):
    ap_code: Optional[int]
    classification: ItemClassification
    count: Optional[int] = 1


class LocData(NamedTuple):
    ap_code: Optional[int]
    region: Optional[str]
