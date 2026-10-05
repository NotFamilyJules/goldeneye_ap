"""Archipelago room downloads contain patches, never the base ROM."""
import hashlib
import json
import os
import pkgutil

from worlds.Files import APProcedurePatch, APTokenMixin, APTokenTypes


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
    patch.write_file("slot_data.bin", patch.get_token_binary())

    # 3. Archipelago publishes this player container on the room page.
    filename = world.multiworld.get_out_file_name_base(world.player) + patch.patch_file_ending
    patch.write(os.path.join(output_directory, filename))
