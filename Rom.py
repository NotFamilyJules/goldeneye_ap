# NOT WHAT MAKES CORE PATCHES TO THE ROM OR THE ROM ITSELF #

# This file is for making seed/options specific changes to the GoldenEye 007 ROM.
# This includes randomizing sound effects and music based on the provided slot data.
# This script defines the patch metadata for the Archipelago ROM,
# Then finally outputs a .apge file the player will play from.

import hashlib
import json
import os
import pkgutil
import struct

from worlds.Files import APProcedurePatch, APTokenMixin, APTokenTypes

from .GoldeneyeClient import randomization_stream
from .randomization_tables import MUSIC_BYTES, MUSIC_POOL


# Dound effects that are not finite and loop forever. All other nonzero
# bank entries finish by themselves, even when their sample has a loop.
HELD_SFX = (58, 59, 60, 62, 65, 66, 67, 101, 102, 161,
            162, 163, 193, 194, 204, 216, 218, 225, 246, 255)

# Shared watch-laser/ricochet IDs stay with ricochets, including their firing use.
# UNKNOWN IDS: 44, 103, 205, 206, 207, 254
# ID 104 is the same as body-fall sfx IDs 130..132.
WEAPON_SFX = (1, 3, 4, 5, 6, 11, 12, 45, 46, 47, 48, 49, 50, 89,
              95, 96, 97, 100, 101, 105, *range(106, 120), 121,
              228, 232, 233, 234, 235, 241, 242, 243, 253)
WEAPON_HANDLING_SFX = (45, 50, 89, 232, 233, 234, 235, 241, 242, 243)

# SFX categories for players who don't want adhd simulator 64
SFX_CATEGORIES = {
    "gunfire_explosions_impacts": (
        *(sound for sound in WEAPON_SFX if sound not in WEAPON_HANDLING_SFX),
        *range(169, 183), 2, *range(69, 77), 104, 120,
        *range(123, 134), 185, 208, 209, 212, 213, 217, 220, 221,
        224, 230, 231, 239, 240, 261),
    "voices": (13, 14, 15, 54, 55, 56, 57, 68, 84, 98, 99,
               *range(134, 159), 183, 257),
    
    # Ricochets and flybys are extremely disorientating if not only shuffled within their own category.
    "ricochets_flybys": (*range(19, 43), 91, 92, 93, *range(164, 169)), 
    "casings": (90, 122),

    "machinery_ambience": (7, 8, 9, 51, 52, 53, *range(58, 68), 102, 187,
                           188, *range(191, 198), *range(199, 205), 210, 211,
                           214, 215, 216, 218, 219, 222, 223, 225, 226,
                           *range(248, 253)),
                           
    "electronics_interface": (*WEAPON_HANDLING_SFX, 10, 16, 17, 18, 43, *range(77, 84), 85, 86,
                              87, 88, 94, 159, 160, 161, 162, 163, 184, 186,
                              189, 190, 198, 227, 229, 236, 237, 238, 244,
                              245, 246, 247, 255, 256, 258, 259, 260),
}


def build_rom_audio(slot_data):
    # 1. Choose broad sound pools. Off leaves the native identity mapping.
    mode = slot_data["options"].get("sfx_randomization", 4)
    sounds = list(range(262))
    if mode == 1:
        categories = {"weapons": WEAPON_SFX}
    elif mode == 2:
        categories = SFX_CATEGORIES
    elif mode == 3:
        categories = {"all": tuple(range(1, 262))}
    else:
        categories = {}

    # 2. Cycle each pool within its stop behavior. Native chains stay intact.
    # Keep true_random byte-identical to the existing all-SFX seed mapping.
    for category, entries in categories.items():
        feature = "all-sfx-v1" if mode == 3 else f"sfx-categories-v1:{category}"
        stream = randomization_stream(slot_data["Seed"], slot_data["Slot"], feature)
        for held in (False, True):
            pool = [sound for sound in entries if (sound in HELD_SFX) == held]
            stream.shuffle(pool)
            for original, replacement in zip(pool, pool[1:] + pool[:1]):
                sounds[original] = replacement
    writes = [(0xBFE800, struct.pack(">262I", *sounds))]

    # 3. Frontend hooks read this table before AP connects. Tables are outside
    # the N64 checksum region, so every room keeps the compiled ROM's checksum.
    music = list(range(63))
    if slot_data["options"].get("randomize_music", 0):
        stream = randomization_stream(slot_data["Seed"], slot_data["Slot"], "frontend-music-v1")
        for original in (2, 23, 44):
            music[original] = stream.choice([track for track in MUSIC_POOL
                                            if track != original and MUSIC_BYTES[track] <= 6344])
    writes.append((0xBFED00, struct.pack(">63I", *music)))
    return writes


class GoldeneyeProcedurePatch(APProcedurePatch, APTokenMixin):
    game = "GoldenEye 007"
    hash = "70c525880240c1e838b8b1be35666c3b"
    patch_file_ending = ".apge"
    result_file_ending = ".z64"
    procedure = [("apply_bsdiff4", ["base_patch.bsdiff4"]),
                 ("apply_tokens", ["slot_data.bin"])]

    @classmethod
    def get_source_data(cls):
        from . import GoldeneyeWorld
        with open(GoldeneyeWorld.settings.rom_file, "rb") as source:
            data = source.read()
        if hashlib.md5(data).hexdigest() != cls.hash:
            raise ValueError("Select the original GoldenEye 007 USA .z64 ROM.")
        return data


def generate_output(world, output_directory):
    # 1. Bundle the compiled changes without needing a ROM on the seed host.
    patch = GoldeneyeProcedurePatch(player=world.player,
                                   player_name=world.multiworld.player_name[world.player])
    patch.write_file("base_patch.bsdiff4", pkgutil.get_data(__package__, "base_patch.bsdiff4"))

    # 2. Store this slot's identity in verified padding before the native payload.
    identity = json.dumps({"slot": patch.player_name, "seed": world.multiworld.seed_name},
                          ensure_ascii=True).encode("ascii")
    patch.write_token(APTokenTypes.WRITE, 0xBFF800, b"GEAP0001" + identity + b"\0")
    # 3. Audio starts before AP connects, so put its slot choices in this ROM.
    slot_data = {"Seed": world.multiworld.seed_name, "Slot": patch.player_name,
                 "options": {name: getattr(world.options, name).value
                             for name in ("sfx_randomization", "randomize_music")}}
    for offset, data in build_rom_audio(slot_data):
        patch.write_token(APTokenTypes.WRITE, offset, data)
    patch.write_file("slot_data.bin", patch.get_token_binary())

    # 4. Archipelago publishes this player container on the room page.
    filename = world.multiworld.get_out_file_name_base(world.player) + patch.patch_file_ending
    patch.write(os.path.join(output_directory, filename))
