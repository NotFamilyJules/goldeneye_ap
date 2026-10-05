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
