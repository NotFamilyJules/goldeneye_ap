from BaseClasses import Location, Item, ItemClassification


class GoldeneyeLocation(Location):
    game = "GoldenEye 007"


class GoldeneyeItem(Item):
    game = "GoldenEye 007"


class ItemData:
    def __init__(self, ap_code, classification: ItemClassification, count: int = 1):
        self.ap_code = ap_code
        self.classification = classification
        self.count = count


class LocData:
    def __init__(self, ap_code, region):
        self.ap_code = ap_code
        self.region = region
