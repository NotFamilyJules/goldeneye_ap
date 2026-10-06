"""Archipelago room downloads contain patches, never the base ROM."""
import hashlib
import json
import os
import pkgutil
import struct

from worlds.Files import APProcedurePatch, APTokenMixin, APTokenTypes

from .GoldeneyeClient import randomization_stream
from .randomization_tables import MUSIC_BYTES, MUSIC_POOL


# Complete native chains containing an indefinite envelope. All other nonzero
# bank entries finish by themselves, even when their sample has a loop.
HELD_SFX = (58, 59, 60, 62, 65, 66, 67, 101, 102, 161,
            162, 163, 193, 194, 204, 216, 218, 225, 246, 255)


def build_rom_audio(slot_data):
    # 1. Shuffle every audible SFX ID once per slot, within its stop behavior.
    # A shuffled cycle changes every ID. Zero stays silent; chains stay native.
    sounds = list(range(262))
    if slot_data["options"].get("randomize_all_sfx", 0):
        stream = randomization_stream(slot_data["Seed"], slot_data["Slot"], "all-sfx-v1")
        for pool in ([sound for sound in range(1, 262) if sound not in HELD_SFX], list(HELD_SFX)):
            stream.shuffle(pool)
            for original, replacement in zip(pool, pool[1:] + pool[:1]):
                sounds[original] = replacement
    writes = [(0xBFE800, struct.pack(">262I", *sounds))]

    # 2. Frontend hooks read this table before AP connects. Tables are outside
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
            raise ValueError("Select the original GoldenEye 007 USA .z64 ROM, not an already patched ROM.")
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
                             for name in ("randomize_all_sfx", "randomize_music")}}
    for offset, data in build_rom_audio(slot_data):
        patch.write_token(APTokenTypes.WRITE, offset, data)
    patch.write_file("slot_data.bin", patch.get_token_binary())

    # 4. Archipelago publishes this player container on the room page.
    filename = world.multiworld.get_out_file_name_base(world.player) + patch.patch_file_ending
    patch.write(os.path.join(output_directory, filename))
