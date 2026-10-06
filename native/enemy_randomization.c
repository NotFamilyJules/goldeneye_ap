/* Native per-creation selection recovered from Random-eye-zer v1.1.
 * USA addresses. No AP seed mapping, character-type map, or Python RNG.
 */
typedef unsigned int u32;
typedef unsigned char u8;
static const u8 bodies[] = {0, 1, 2, 3, 4, 17, 18, 20, 21, 22, 23, 24, 29, 33, 34, 32, 35, 28, 37, 38, 39, 40, 36, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 27, 19, 5};
static const u8 traits[] = {1, 1, 1, 1, 1, 1, 3, 3, 3, 0, 3, 2, 3, 3, 2, 3, 2, 1, 1, 1, 1, 3, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 3, 1, 1, 1, 0};
static const u8 male_heads[] = {57, 54, 55, 62, 59, 56, 58, 53, 52, 51, 42, 43, 44, 45, 46, 47, 48, 49, 50, 63, 64, 65, 66, 67, 68};
static const u8 female_heads[] = {70,71,72,73};
/* The hack's sixteen unconditional model/weapon pairs. */
static const unsigned short weapons[] = {
    (208<<8)|19, (211<<8)|25, (185<<8)|24, (192<<8)|15,
    (190<<8)|18, (207<<8)|16, (210<<8)|17, (197<<8)|14,
    (188<<8)|13, (194<<8)|12, (189<<8)|10, (195<<8)|9,
    (184<<8)|8, (193<<8)|7, (205<<8)|6, (191<<8)|4
};
static u32 random_next(void) { return ((u32 (*)(void))0x7000A450)(); }
u32 choose_appearance(void) {
    u32 body = bodies[random_next() % 36];
    u32 head = 0xffff;
    if (!(traits[body] & 2)) {
        head = traits[body] & 1 ? male_heads[random_next() % 25]
                                : female_heads[random_next() % 4];
    }
    return (body << 16) | head;
}
u32 choose_weapon(u32 original) {
    if (!((original >= 2 && original <= 25) || original == 30 || original == 31))
        return 0;
    return weapons[random_next() % 16];
}

/* Random-eye-zer's player constructor omits the separate head allocation for
 * bodies with built-in heads. The vanilla player constructor assumes two
 * models, unlike the enemy constructor. Keep its original layout otherwise.
 */
__attribute__((section(".bond_support")))
u32 prepare_bond_body(u32 *frame, u32 file_id) {
    u32 body_bytes = ((u32 (*)(u32))0x7F0BD188)(file_id);
    if ((int)frame[0x40 / 4] >= 0)
        return body_bytes;
    u32 body_header = frame[0xFC / 4];
    u32 buffer = frame[0xF0 / 4];
    u32 offset = (body_bytes + 63) & ~63;
    u32 animation = buffer + offset;
    frame[0x38 / 4] = animation;
    offset = (offset + 0xFB) & ~63;
    ((void (*)(u32))0x7F075CF4)(body_header);
    u32 count = *(short *)(body_header + 0x14) + 10;
    frame[0xE8 / 4] = (offset + count * 4 + 63) & ~63;
    ((void (*)(u32, u32, u32))0x7F075FAC)(animation, body_header, buffer + offset);
    *(short *)(animation + 2) = count;
    frame[0xF8 / 4] = 0;
    return body_bytes;
}
