import hashlib
import os
import runpy


INPUT_ROM = r"C:\goldeneye_ap\GoldenEye 007 (U) [!].z64"
OUTPUT_ROM = r"C:\goldeneye_ap\test_build\Goldeneye 007 AP ROM.z64"



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
    (0x0850E4, 0x0FC228C3, 0x00000000),
    (0x0851E8, 0x0FC231C9, 0x0FC23506),  # option-gated native prop acquisition at 7F08D418

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

# Guard guns: 9mm only when the client publishes gun_pickup=2.
# In-place US collect_or_interact_object ammo block plus collectability wrapper.
# Native acquisition NOPs above remain in force. See guard_ammo_report.md.
GUARD_AMMO_PATCHES = [
    (0x085040, 0x0FC1A50B, 0xAFA30068),  # sw v1, 0x68(sp): preserve native collection/removal type
    (0x085044, 0xAFA30068, 0x3C088008),  # lui t0, 0x8008
    (0x085048, 0x8FA30068, 0x9108F208),  # lbu t0, -0xDF8(t0): AP gun_pickup option
    (0x08504C, 0x10400055, 0x24090002),  # li t1, 2: just_ammo
    (0x085050, 0x00408025, 0x15090015),  # bne t0, t1, finish
    (0x085054, 0x8FA40048, 0x8FA80048),  # lw t0, 0x48(sp): collected WeaponObjRecord
    (0x085058, 0x0FC13F3E, 0x8D090008),  # lw t1, 8(t0): object flags
    (0x08505C, 0xAFA30068, 0x31294000),  # andi t1, t1, 0x4000: ASSIGNEDTOCHR
    (0x085060, 0x8FA30068, 0x11200011),  # beqz t1, finish: preplaced AP objects get no ammo
    (0x085064, 0x1840004F, 0x81080080),  # lb t0, 0x80(t0): weapon ID
    (0x085068, 0xAFA20034, 0x2D080021),  # sltiu t0, t0, 33: exclude mission items and AP token
    (0x08506C, 0x02002025, 0x1100000E),  # beqz t0, finish
    (0x085070, 0x0FC1A490, 0x00000000),  # nop
    (0x085074, 0xAFA30068, 0x0FC1A490),  # jal check_cur_player_ammo_amount_in_inventory
    (0x085078, 0xAFA20024, 0x24040001),  # li a0, 1: AMMO_9MM, regardless of dropped weapon
    (0x08507C, 0x0FC1A4B5, 0xAFA20024),  # sw v0, 0x24(sp): current 9mm reserve
    (0x085080, 0x02002025, 0x3C088003),  # lui t0, 0x8003
    (0x085084, 0x8FAA0024, 0xC5000B28),  # lwc1 f0, 0xB28(t0): native g_SoloAmmoMultiplier
    (0x085088, 0x8FA30068, 0x3C084120),  # lui t0, 0x4120: 10.0f
    (0x08508C, 0x02002025, 0x44881000),  # mtc1 t0, f2
    (0x085090, 0x0142082A, 0x46020002),  # mul.s f0, f0, f2
    (0x085094, 0x50200044, 0x4600000D),  # trunc.w.s f0, f0
    (0x085098, 0x24010001, 0x44080000),  # mfc1 t0, f0: 20 / 15 / 10 rounds
    (0x08509C, 0x0FC1A490, 0x8FA50024),  # lw a1, 0x24(sp)
    (0x0850A0, 0xAFA30068, 0x0FC1A44C),  # jal give_cur_player_ammo: native clamp to 800; a0 is still 1
    (0x0850A4, 0x8FAB0034, 0x00A82821),  # addu a1, a1, t0
    (0x0850A8, 0x02002025, 0x1000003E),  # finish: b native removal path
    (0x0850AC, 0x0FC1A44C, 0x8FA30068),  # lw v1, 0x68(sp)
    (0x0850B0, 0x004B2821, 0x3C088008),  # collectability helper: lui t0, 0x8008
    (0x0850B4, 0x8FAC0044, 0x9108F208),  # lbu t0, -0xDF8(t0)
    (0x0850B8, 0x8FA30068, 0x24090002),  # li t1, 2
    (0x0850BC, 0x8FAD0074, 0x15090006),  # bne t0, t1, original_inventory_check
    (0x0850C0, 0x55800039, 0x8C680008),  # lw t0, 8(v1): weapon flags
    (0x0850C4, 0x24010001, 0x31084000),  # andi t0, t0, 0x4000
    (0x0850C8, 0x11A00036, 0x11000003),  # beqz t0, original_inventory_check
    (0x0850CC, 0x02002025, 0x00000000),  # nop
    (0x0850D0, 0x8FA50034, 0x03E00008),  # jr ra: guard drop may reach normal physical collection
    (0x0850D4, 0x0FC13E7E, 0x00001025),  # move v0, zero: no acquisition is performed
    (0x0850D8, 0xAFA30068, 0x0BC230C5),  # j bondinvHasInvItem: unchanged preplaced/off behavior
    (0x0850DC, 0x10000031, 0x00000000),  # nop
    (0x0853A8, 0x0FC230C5, 0x0FC14160),  # jal wrapper at 7F050580
]

# Key Item Receive
# Keep each native inventory check first. AP permission is only the fallback when the native check says no.
KEY_ITEM_RECEIVE_PATCHES = [
    (0x0C19A8, 0x27BDFFF8, 0x3C028008),
    (0x0C19AC, 0xAFB00004, 0x8C42F200),
    (0x0C19B4, 0x00808025, 0x00000000),
    (0x0C19B8, 0x00001025, 0x00000000),
    (0x0C1A04, 0x02026024, 0x00826024),
    (0x0C1A08, 0x560C0004, 0x548C0004),
    (0x0C1A10, 0x10000007, 0x10000008),
    (0x0C1A1C, 0x50650004, 0x50650003),
    (0x0C1A20, 0x00001025, 0x00000000),
    (0x0C1A2C, 0x00001025, 0x00821024),
    (0x0C1A30, 0x8FB00004, 0x00441026),
    (0x0C1A34, 0x03E00008, 0x03E00008),
    (0x0C1A38, 0x27BD0008, 0x2C420001),
    (0x0C1A94, 0x50430004, 0x50430003),
    (0x0C1AA4, 0x00001025, 0x3C088008),
    (0x0C1AA8, 0x03E00008, 0x9102F207),
    (0x0C1AAC, 0x00000000, 0x03E00008),
]

# AP watch entries use the game's allocated InvItem pool, never a PropRecord.
# Type 0x10001 is ignored by native weapon cycling/acquisition. Only the watch
# count/index/model paths read its low half (1). value packs semantic ID/model;
# text packs the native short/long language IDs. No new RAM arena is required.
KEY_WATCH_PATCHES = [
    (0x0C1B9C, 0x8CA20000, 0x94A20002),  # count: initial type
    (0x0C1C2C, 0x8CA20000, 0x94A20002),  # count: next type
    (0x0C1C7C, 0x8CA20000, 0x94A20002),  # index: initial type
    (0x0C1D3C, 0x8CA20000, 0x94A20002),  # index: next type
    (0x0C1DF4, 0x8C440000, 0x94440002),  # model: type
    (0x0C1E30, 0x8C620004, 0x94620006),  # model: low half of value
]


def key_watch_name_words(text_offset, virtual_offset, default_call):
    # Same native fallback behavior for props, weapons and all-guns mode.
    # The tagged entry reads a language ID directly, without dereferencing a prop.
    return [
        0x27BDFFE0, 0xAFBF0014, 0x0FC23442, 0xAFA40020,
        0x10400023, 0x00002025, 0x8C480000, 0x3C090001,
        0x35290001, 0x11090019, 0x00000000, 0x24090002,
        0x15090006, 0x8C440004, 0x8C840004, 0x0FC23487,
        0xAFA00018, 0x10000006, 0x00000000, 0x24090001,
        0x5509000A, 0x00002025, 0x0FC23497, 0xAFA40018,
        0x10400005, 0x00000000, 0x8C440000 | text_offset,
        0x14800008, 0x8C480008, 0xAFA80018, 0x8FA40018,
        default_call, 0x00000000, 0x10000011, 0x00000000,
        0x94440000 | virtual_offset, 0x0FC30776, 0x00000000,
        0x1000000C, 0x00000000, 0x3C088008, 0x8D08A0B0,
        0x8D0811EC, 0x1100FFF3, 0x00000000, 0x8FA80020,
        0x29090020, 0x1120FFEF, 0x00000000, 0x1000FFED,
        0x25040001, 0x8FBF0014, 0x03E00008, 0x27BD0020,
    ]


def patch_key_watch_names(patched):
    # US ROM function bodies, including their exact original instruction hashes.
    for offset, field, virtual_field, fallback, expected in [
        (0xC1E70, 0x14, 8, 0x0FC19C2A, "4e7dc8c3b1bd787881e66eaf79f769365374292f7044c355875f120b7f13d754"),
        (0xC1F64, 0x18, 10, 0x0FC19C37, "5d8757b749ff42d5760318b19f939fa8a6836bdb8427a1b5f9ee1a5c12bd8c45"),
        (0xC20F8, 0x0C, 8, 0x0FC19C10, "f514e4d96fb9ff7673c0503a7a3b48f48b02b5a29b0fcf145754503000aa94b7"),
        (0xC21EC, 0x10, 10, 0x0FC19C1D, "bd05e9eb33a221fc3b4e3918b697c0dc0085734b0c70a30f98e2a18fcec7c324"),
    ]:
        if hashlib.sha256(patched[offset:offset + 244]).hexdigest() != expected:
            raise SystemExit(f"Unexpected watch name instructions at 0x{offset:X}")
        words = key_watch_name_words(field, virtual_field, fallback)
        assert len(words) * 4 <= 244
        for index, word in enumerate(words):
            write_u32_be(patched, offset + index * 4, word)

    # Six words in the first getter's unused, hash-checked tail. Tail-branch to
    # bondinvAddPropToInv only for unshuffled native items. The shuffled path
    # retains the prior no-grant behavior; guard-gun code is untouched.
    offset = 0xC1F48
    target = 0xC1254
    branch = (target - (offset + 8 + 4)) // 4
    words = [0x3C088008, 0x9108F209, 0x15000000 | (branch & 0xFFFF),
             0x00000000, 0x03E00008, 0x00000000]
    for index, word in enumerate(words):
        write_u32_be(patched, offset + index * 4, word)

    # watch.c:sub_GAME_7F0A8378. Preserve A/Z/Start selection semantics, but
    # Passive documents/keys never equip a hand. DAT (73) retains native use.
    # This fits entirely in the original function and uses its original calls.
    offset = 0xDCEA8
    expected = "254fc91924217c19214e0d8e983f1d7d445b926494b55d05483d02216ead50a5"
    if hashlib.sha256(patched[offset:offset + 172]).hexdigest() != expected:
        raise SystemExit("Unexpected watch selection instructions")
    words = [
        0x27BDFFE0, 0xAFBF0014, 0x00002025, 0x0C0030EB,
        0x3405B000, 0x10400022, 0xAFA20018, 0x3C048004,
        0x0FC234AA, 0x8C8409B8, 0x0FC0DB54, 0xAFA2001C,
        0x1440001B, 0x00000000, 0x8FA80018, 0x3108A000,
        0x15000006, 0x00000000, 0x0FC17674, 0x00002025,
        0x8FA5001C, 0x10450012, 0x00000000, 0x8FA5001C,
        0x0FC176D5, 0x00002025, 0x24040001, 0x0FC176D5,
        0x00002825, 0x3C048004, 0x0FC23634, 0x8C8409B8,
        0x2408000A, 0x3C098004, 0xAD2809C4, 0x3C048006,
        0x8C843720, 0x2405009F, 0x0C002382, 0x00003025,
        0x8FBF0014, 0x03E00008, 0x27BD0020,
    ]
    assert len(words) * 4 == 172
    for index, word in enumerate(words):
        write_u32_be(patched, offset + index * 4, word)


def patch_semantic_object_ownership(patched):
    # The three remaining getter tails are covered by the full original-body
    # hash checks above. A single leaf query walks stage-owned semantic nodes.
    # a0=setup tag, v0=owned. No original object or prop is dereferenced.
    def branch(opcode, here, target):
        return opcode | (((target - here - 4) // 4) & 0xFFFF)

    def jump(offset, link=False):
        address = 0x7F000000 + offset - 0x34B30
        return (0x0C000000 if link else 0x08000000) | ((address >> 2) & 0x3FFFFFF)

    a, b, c = 0xC203C, 0xC21D0, 0xC22C4
    blocks = {
        a: [0x3C088008, 0x8D08A0B0, 0x8D0911E0, 0x3C0B0001,
            0x356B0001, jump(b), 0x01204025],
        b: [branch(0x11000000, b, c + 20), 0x00001025, 0x8D0A0000,
            branch(0x154B0000, b + 12, c + 8), 0x910A0004, jump(c), 0],
        c: [branch(0x11440000, c, c + 20), 0x24020001, 0x8D08000C,
            branch(0x15090000, c + 12, b + 8), 0x00001025, 0x03E00008, 0],
    }
    for offset, words in blocks.items():
        for index, word in enumerate(words):
            write_u32_be(patched, offset + index * 4, word)

    # ObjectiveCollectObject: ownership is checked BEFORE object existence and
    # health. With no semantic ownership, preserve every native failure check.
    offset = 0x8BE60
    if hashlib.sha256(patched[offset:offset + 76]).hexdigest() != "2fca6b3164c9469d6dda8bae4d28a0bedcb0d28830ffe92f8508437d71dfde57":
        raise SystemExit("Unexpected native collection-objective instructions")
    complete, failed = 0x8BF68, 0x8BF1C
    words = [jump(a, True), 0x8E440004,
             branch(0x14400000, offset + 8, complete), 0x8E440004,
             0x0FC15C30, 0, branch(0x10400000, offset + 24, failed), 0x00408025,
             0x8C440010, branch(0x10800000, offset + 36, failed), 0,
             0x0FC13BCD, 0x02002025, branch(0x10400000, offset + 52, failed),
             0x8E040010, 0x0FC233F8, 0,
             branch(0x10000000, offset + 68, complete), 0x00408825]
    for index, word in enumerate(words):
        write_u32_be(patched, offset + index * 4, word)

    # AI_IFBondCollectedObject has the same tag semantics. Reuse the adjacent
    # three-byte predicate's unchanged native label/advance tail. Verify that
    # tail too, rather than assuming its register contract or command length.
    offset = 0x6B84C
    if hashlib.sha256(patched[offset:0x6B8D0]).hexdigest() != "4b2103c025f53b788bc4e38bbec29b1860fd3c7c16357d53688cc2670c3c4718":
        raise SystemExit("Unexpected native AI collection predicate instructions")
    words = [jump(a, True), 0x92240001,
             branch(0x14400000, offset + 8, 0x6B8AC), 0x02C02025,
             0x0FC15C30, 0x92240001,
             branch(0x10400000, offset + 24, 0x6B8C4), 0,
             0x0FC233F8, 0x8C440010, jump(0x6B8A4), 0]
    for index, word in enumerate(words):
        write_u32_be(patched, offset + index * 4, word)
    # bondinvHasPropInInv compares pointers without dereferencing its argument;
    # NULL cannot equal any legitimate native inventory prop. This allows the
    # native predicate above to retain that null-object outcome without a second
    # branch. The unused tail holds the watch's passive-item predicate.
    offset = 0x6B880
    words = [0x2458FFC2, 0x3B19000B, 0x2F020016, 0x2F390001, 0x03E00008, 0x00591026]
    for index, word in enumerate(words):
        write_u32_be(patched, offset + index * 4, word)

    # ObjectiveFailCondition alone masks source-destruction failures covered by
    # AP collection ownership. Keep native stage flags and all AI queries intact.
    # The mask occupies the already guarded/reset key-state word's upper half.
    offset = 0x8BF68
    expected = "660c80f8ffc0a3cf9f7e72ed99d2a2448449ee52c3daf6349d6a5fb042acea61"
    if hashlib.sha256(patched[offset:offset + 44]).hexdigest() != expected:
        raise SystemExit("Unexpected native objective status-combination instructions")
    # Native statuses are incomplete=0, complete=1, failed=2. Its original
    # combination is: take current when prior is complete or current is failed.
    # Six instructions preserve that truth table; five freed words hold a leaf
    # wrapper that tail-calls the original chrHasStageFlag without stack changes.
    words = [0x12740003, 0x24080002, 0x16280008, 0,
             0x10000006, 0x02209825,
             0x3C088008, 0x9508F204, 0x01004027, 0x0BC0CCCE, 0x00A82824]
    for index, word in enumerate(words):
        write_u32_be(patched, offset + index * 4, word)
    if read_u32_be(patched, 0x8BE48) != 0x0FC0CCCE:
        raise SystemExit("Unexpected native objective failure predicate call")
    write_u32_be(patched, 0x8BE48, jump(0x8BF80, True))

def patch_native_handoff_feedback(patched):
    # 1. Verify the native key feedback block and scripted handoff's advance.
    for start, end, expected in [
        (0x84DF4, 0x84E40, "1b56e0d3bd2db97767cecc1a96e8db5055e8e432ad3931b7355ec14825a833b1"),
        (0x6BD20, 0x6BD2C, "5fc096d2fcbab3d03563827e8f501cea555299ad84b530b4751edc50fb15f224"),
    ]:
        if hashlib.sha256(patched[start:end]).hexdigest() != expected:
            raise SystemExit("Unexpected native handoff feedback instructions")

    def jump(offset):
        return 0x08000000 | (((0x7F000000 + offset - 0x34B30) >> 2) & 0x3FFFFFF)

    # 2. Play the key sound only before this exact prop belongs to Bond.
    # At the key case, a0 is the source prop and t7 is g_CurrentPlayer.
    # Keep native pickup/reparenting and the randomized inventory grant unchanged.
    # The existing suppressed key text leaves room for the handoff advance below.
    words = [
        0x8C88001C,  # lw t0, parent(a0)
        0x8DE900A8,  # lw t1, player_prop(t7)
        0x1109000E,  # beq t0, t1, native key completion at 0x84E38
        0x240500E5,  # delay: key sound ID
        0x3C048006, 0x8C843720, 0x0C002382, 0x00003025,
        jump(0x84E38), 0,
    ]
    for index, word in enumerate(words):
        write_u32_be(patched, 0x84DF4 + index * 4, word)

    # 3. Skip only TextPrintBottom immediately following BondCollectObject.
    # s1 points at the current AI command; s2 is its offset. Advance both by
    # the handoff's two bytes, plus the message's three bytes when present.
    # All other script commands and dialogue keep their normal progression.
    helper = 0x84E1C
    dispatch = 0x6A0BC
    branch_offset = (dispatch - (helper + 8 + 4)) // 4
    words = [
        0x92280002,  # lbu t0, next opcode(s1)
        0x390800C2,  # xori t0, t0, AI_TextPrintBottom
        0x15000000 | (branch_offset & 0xFFFF),
        0x26310002,  # delay: advance command pointer past handoff
        0x26520003,  # advance offset past the suppressed message
        jump(dispatch),
        0x26310003,  # delay: advance command pointer past the message
    ]
    for index, word in enumerate(words):
        write_u32_be(patched, helper + index * 4, word)
    write_u32_be(patched, 0x6BD20, jump(helper))
    write_u32_be(patched, 0x6BD24, 0x26520002)


def patch_startup_weapon_grants(patched):
    # 1. Verify the US intro-item block before replacing its grant/draw boundary.
    # bondviewLoadSetupIntroSection, including the existing slappers override.
    start, end = 0x03A634, 0x03A6A8
    expected = "d794f0c6e18b0e1c1fb771976c5e10d2108baf6dfc5021f4f8ff70f79f3908f2"
    if hashlib.sha256(patched[start:end]).hexdigest() != expected:
        raise SystemExit("Unexpected native startup inventory instructions")

    # 2. Keep projectile initialization and native document/gadget grants.
    # Guns (IDs below ITEM_BOMBCASE=33) come only from the client's AP loadout.
    # Otherwise A can queue a vanilla gun before sync, outliving its inventory node.
    words = [
        0x0FC015C4, 0x8E040004,  # load right projectile models
        0x8E040008, 0x04800003, 0,  # no left item: go to grant filter
        0x0FC015C4, 0,          # load left projectile models
        0x8E040004,             # a0 = right item
        0x2C810021,             # sltiu at, a0, 33
        0x14200009, 0x8E050008, # gun: skip grant; delay: a1 = left item
        0x04A00005, 0,          # negative left item: single grant
        0x0FC23143, 0,          # bondinvAddDoublesInvItem(a0, a1)
        0x10000003, 0,          # go to startup draw
        0x0FC23122, 0,          # bondinvAddInvItem(a0)

        # 3. Retain the shared slappers/right and unarmed/left startup draw.
        # The native fallback still adds slappers when there are no intro items.
        0x3C018008, 0x240F0001,
        0xAC2F99E0, 0xAC2099E4,
        0xAFAF007C, 0, 0, 0,    # starting weapon selected
        0x1000009C, 0x26100010,  # original next-intro branch and record advance
    ]
    assert len(words) * 4 == end - start
    for index, word in enumerate(words):
        write_u32_be(patched, start + index * 4, word)


def build_output_rom(rom: bytes) -> bytes:
    patched = bytearray(rom)

    # alloc_additional_item_slots: extend the actual stage allocation, never a
    # pointer into spare RAM. Native alignment, LINK additions, initialization
    # and stage teardown remain intact. mempAllocBytesInBank bounds the arena.
    data = runpy.run_path(os.path.join(os.path.dirname(__file__), "client_data.py"))
    base_slots = 30 + data["AP_INVENTORY_EXTRA_SLOTS"]
    assert 30 < base_slots <= 128
    offset = 0x03ADA0
    if read_u32_be(patched, offset) != 0x248E001E:
        raise SystemExit("Unexpected alloc_additional_item_slots instruction")
    write_u32_be(patched, offset, 0x248E0000 | base_slots)

    for offset, expected, replacement in PATCHES + KEY_ITEM_RECEIVE_PATCHES + GUARD_AMMO_PATCHES + KEY_WATCH_PATCHES: # Apply the above patches to the rom
        actual = read_u32_be(patched, offset)
        if actual != expected:
            raise SystemExit(
                f"Unexpected word at 0x{offset:06X}: 0x{actual:08X} expected 0x{expected:08X}"
            )
        write_u32_be(patched, offset, replacement)

    patch_key_watch_names(patched)
    patch_semantic_object_ownership(patched)
    patch_native_handoff_feedback(patched)

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

    patch_startup_weapon_grants(patched)

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
