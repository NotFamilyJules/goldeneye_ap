import hashlib
import os


INPUT_ROM = r"C:\goldeneye_ap\GoldenEye 007 (U) [!].z64"
OUTPUT_ROM = r"C:\goldeneye_ap\Goldeneye 007 AP ROM.z64"



#################################################################################################################################
############################################### FUNCTIONS TO READ AND WRITE ROM #################################################
#################################################################################################################################

def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def read_file(path: str) -> bytes:
    with open(path, "rb") as file:
        return file.read()


def write_file(path: str, data: bytes) -> None:
    with open(path, "wb") as file:
        file.write(data)

def read_u32_be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], "big")


def write_u32_be(data: bytearray, offset: int, value: int) -> None:
    data[offset:offset + 4] = value.to_bytes(4, "big")

#################################################################################################################################
############################################### N64 HEADER CRC RECALCULATION ####################################################
####### The checksum is calculated from the first megabyte of the game's data and from the CIC-chip checksum value. #############
#################################################################################################################################

def calc_n64_cksum_6102(data: bytes) -> tuple[int, int]:
    seed = 0xF8CA4DDB
    end_offset = 0x100000
    rom_offset = 0x1000
    current_offset = 0

    seed = (seed + 1) & 0xFFFFFFFF
    a3 = seed
    t2 = seed
    t3 = seed
    s0 = seed
    a2 = seed
    t4 = seed

    while current_offset != end_offset:
        value = read_u32_be(data, rom_offset)
        total = (a3 + value) & 0xFFFFFFFF

        if total < a3:
            t2 = (t2 + 1) & 0xFFFFFFFF

        rotate = value & 0x1F
        if rotate == 0:
            rotated = value
        else:
            rotated = ((value << rotate) | (value >> (32 - rotate))) & 0xFFFFFFFF

        a3 = total
        t3 = (t3 ^ value) & 0xFFFFFFFF
        s0 = (s0 + rotated) & 0xFFFFFFFF

        if a2 < value:
            a2 = (a2 ^ a3 ^ value) & 0xFFFFFFFF
        else:
            a2 = (a2 ^ rotated) & 0xFFFFFFFF

        t4 = (t4 + (value ^ s0)) & 0xFFFFFFFF

        current_offset += 4
        rom_offset += 4

    crc1 = ((a3 ^ t2) ^ t3) & 0xFFFFFFFF
    crc2 = ((s0 ^ a2) ^ t4) & 0xFFFFFFFF
    return crc1, crc2


def update_n64_header_checksums(data: bytearray) -> tuple[int, int]:
    crc1, crc2 = calc_n64_cksum_6102(data)
    write_u32_be(data, 0x10, crc1)
    write_u32_be(data, 0x14, crc2)
    return crc1, crc2

#################################################################################################################################
#################################################### ROM CHANGES SECTION ########################################################
#################### Words: Each 0x... is one 32-bit big-endian word. These are the exact 4-byte values written. ################
#################### Offset: ROM file offset (not a RAM address), the patcher writes directly at this byte. #####################
#################################################################################################################################

PATCHES = [ # Edits to different stuff all around the code
    
    # Restore object_collectability_routines so native pickup path runs.
    (0x08521C, 0x0FC13803, 0x0FC13803),
    (0x085220, 0xAFA40084, 0xAFA40084),

    # Suppress native lower-left pickup text on the collect_or_interact_object paths
    # that currently pass showstring=1.
    (0x083D18, 0x24050001, 0x24050000),
    (0x085844, 0x24050001, 0x24050000),

    # add_ammo_to_inventory: skip native ammo grant, ammo text, and implicit inventory items.
    (0x0845E8, 0x0FC1A44C, 0x00000000),
    (0x084604, 0x0FC13E7E, 0x00000000),
    (0x084634, 0x0FC23122, 0x00000000),
    (0x084650, 0x0FC23122, 0x00000000),
    (0x084658, 0x0FC23122, 0x00000000),
    (0x084674, 0x0FC23122, 0x00000000),
    (0x084690, 0x0FC23122, 0x00000000),
    (0x0846AC, 0x0FC23122, 0x00000000),
    (0x0846C8, 0x0FC23122, 0x00000000),
    (0x0846E4, 0x0FC23122, 0x00000000),
    (0x084700, 0x0FC23122, 0x00000000),
    (0x08471C, 0x0FC23122, 0x00000000),
    (0x084738, 0x0FC23122, 0x00000000),
    (0x084754, 0x0FC23122, 0x00000000),

    # collect_or_interact_object: skip native weapon/armor/inventory grants.
    (0x084F30, 0x0FC23122, 0x00000000),
    (0x084F4C, 0x0FC17645, 0x00000000),
    (0x084F7C, 0x0FC231D9, 0x00001025),
    (0x084FD4, 0x0FC231D9, 0x00001025),
    (0x0850AC, 0x0FC1A44C, 0x00000000),
    (0x0850E4, 0x0FC228C3, 0x00000000),
    (0x0851E8, 0x0FC231C9, 0x00000000),

    # get_highest_unlocked_difficulty_for_level: keep the menu capped at 00 Agent
    # even if the unlock patch has 007 mode enabled.
    (0x0428E8, 0x24110003, 0x24110002),
    (0x0428FC, 0x24110003, 0x24110002),

    # interface_menu08_difficulty: never highlight 007 even if the row still renders.
    # front.c:3519-3523
    (0x043408, 0x24080003, 0x24080002),

    # interface_menu08_difficulty: safety net for the menu transition path.
    # If selected_difficulty somehow still reaches 3, treat it as the non-007 path.
    # front.c:3566-3568
    (0x043560, 0x24010003, 0x24010004),

]

def build_output_rom(rom: bytes) -> bytes:
    patched = bytearray(rom)

    for offset, expected, replacement in PATCHES: # Apply the above patches to the rom
        actual = read_u32_be(patched, offset)
        if actual != expected:
            raise SystemExit(
                f"Unexpected word at 0x{offset:06X}: 0x{actual:08X} expected 0x{expected:08X}"
            )
        write_u32_be(patched, offset, replacement)

    # Native helper behavior:
    # - read one byte from 0x8007F000 + mission_index
    # - if the byte is 0, return -1 (locked)
    # - otherwise return 2 (unlocked)

    words = [   # One continous change at the offset below
        0x3C088007,  # lui   t0, 0x8007
        0x3508F000,  # ori   t0, t0, 0xF000
        0x01044021,  # addu  t0, t0, a0
        0x91090000,  # lbu   t1, 0(t0)
        0x11200003,  # beq   t1, zero, locked_return
        0x00000000,  # nop
        0x24020002,  # addiu v0, zero, 2
        0x03E00008,  # jr    ra
        0x00000000,  # nop
        0x2402FFFF,  # addiu v0, zero, -1
        0x03E00008,  # jr    ra
        0x00000000,  # nop
    ]

    # Force start each level with slappers
    write_u32_be(patched, 0x03A684, 0xAC2F99E0) # Changes the right-hand startup draw to slappers for every level
    write_u32_be(patched, 0x03A69C, 0xAC2099E4) # Changes the left-hand startup draw to unarmed for every level

    offset = 0x42890
    for index, word in enumerate(words):
        start = offset + (index * 4)
        patched[start:start + 4] = word.to_bytes(4, "big")

    update_n64_header_checksums(patched)
    return bytes(patched)

#################################################################################################################################
#################################################### EXECUTE ROM CHANGES ########################################################
#################################################################################################################################

def main() -> None:
    rom = read_file(INPUT_ROM)
    actual_input_sha1 = sha1_bytes(rom)

    output_rom = build_output_rom(rom)
    write_file(OUTPUT_ROM, output_rom)
    output_sha1 = sha1_bytes(output_rom)

    print(f"Input : {os.path.basename(INPUT_ROM)}")
    print(f"SHA-1 : {actual_input_sha1}")
    print(f"Output: {os.path.basename(OUTPUT_ROM)}")
    print(f"SHA-1 : {output_sha1}")
    print("Rom patched.")


if __name__ == "__main__":
    main()
