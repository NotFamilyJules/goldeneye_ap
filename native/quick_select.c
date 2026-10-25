/* QUICK SELECT: US native inventory, controller input and HUD. */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#define INLINE static inline __attribute__((always_inline))
#define WORD(address) (*(volatile u32 *)(address))
#define CALL(address, result, args) ((result (*) args)(address))
#define TEXT(offset) ((char *)(0xB0BFE000 + (offset)))

typedef struct { int type; u32 value, extra, next, prev; } Item;
typedef struct { u32 identity; int index, right, left; char *name; int passive; } Row;
typedef struct {
    u32 player, pool;
    int open, category, selected, count;
    u32 identity, previous_buttons;
    int repeat_ticks, idle_ticks, direction, released;
    int updates, selections, last_right, last_left;
    Row rows[160];
} Selector;
_Static_assert(sizeof(Selector) <= 0x1000, "Selector exceeds its stage state allocation");

INLINE int valid_address(u32 address, u32 bytes) {
    return address >= 0x80000000 && address <= 0x80800000 - bytes && !(address & 3);
}

INLINE int active(u32 player) {
    return valid_address(player, 0x2A00) && WORD(0x8002A8C0) == 11
        && WORD(0x80036494) == 4 && !WORD(player + 0xD8)
        && !WORD(player + 0x1C8) && !WORD(0x80048370)
        && CALL(0x7F09A464, int, (void))() == 1;
}

INLINE int validate_inventory(u32 player) {
    u32 pool = WORD(player + 0x11E4), head = WORD(player + 0x11E0);
    int maximum = WORD(player + 0x11E8);
    if (maximum < 1 || maximum > 128 || !valid_address(pool, maximum * 20)) return 0;
    if (!head) return 1;
    u32 current = head;
    for (int slot = 0; slot < maximum; slot++) {
        if (current < pool || current >= pool + maximum * 20 || (current - pool) % 20) return 0;
        Item *item = (Item *)current;
        if (item->next < pool || item->next >= pool + maximum * 20 || (item->next - pool) % 20) return 0;
        if (((Item *)item->next)->prev != current) return 0;
        if (item->type == 2) {
            if (!valid_address(item->value, 8) || !valid_address(WORD(item->value + 4), 0x80)) return 0;
        }
        current = item->next;
        if (current == head) return 1;
    }
    return 0;
}

INLINE int usable(u32 player, int weapon) {
    /* Native ammunition distinguishes consumable gadgets from reusable devices. */
    int ammo = CALL(0x7F06942C, int, (int))(weapon);
    int consumable = weapon == 3 || (weapon >= 26 && weapon <= 29)
        || (weapon >= 33 && ammo > 0);
    if (!consumable) return 1;
    if (ammo <= 0 || ammo >= 30) return 0;
    int total = WORD(player + 0x1130 + ammo * 4);
    if (WORD(player + 0x870) == (u32)weapon) total += WORD(player + 0x89C);
    if (WORD(player + 0xC18) == (u32)weapon) total += WORD(player + 0xC44);
    return total > 0;
}

INLINE void add_row(Selector *state, u32 identity, int index, int right, int left, char *name, int passive) {
    for (int row = 0; row < state->count; row++) {
        if (state->rows[row].identity == identity
            || (passive && state->rows[row].passive && state->rows[row].name == name)) return;
    }
    if (state->count == 160) return;
    Row *row = &state->rows[state->count++];
    row->identity = identity; row->index = index; row->right = right; row->left = left;
    row->name = name; row->passive = passive;
}

INLINE void read_entries(Selector *state) {
    u32 player = state->player;
    state->count = 0;
    int count = CALL(0x7F08D038, int, (void))();
    for (int index = 0; index < count; index++) {
        Item *item = CALL(0x7F08D108, Item *, (int))(index);
        int right = CALL(0x7F08D2A8, int, (int))(index);
        int passive = (right >= 62 && right <= 83 && right != 73) || right == 0;
        u32 identity = right;
        if (item && item->type == 0x10001) {
            if (passive) identity = 0x10000 | ((item->value >> 16) & 255);
        } else if (item && item->type == 2 && passive) {
            identity = item->value;
        }
        int category = passive || right >= 33;
        if (category != state->category || (!passive && !usable(player, right))) continue;
        char *name = CALL(0x7F08D340, char *, (int))(index);
        add_row(state, identity, index, right, 0, name, passive);
        /* Keep native single/dual order, without manufacturing a second ownership list. */
        if (!category) {
            u32 head = WORD(player + 0x11E0), current = head;
            for (int visited = 0; current && visited < (int)WORD(player + 0x11E8); visited++) {
                Item *pair = (Item *)current;
                if (pair->type == 3 && pair->value == (u32)right)
                    add_row(state, right | (pair->extra << 8), index, right, pair->extra, name, 0);
                current = pair->next;
                if (current == head) break;
            }
            if (WORD(player + 0x11EC)
                && CALL(0x7F05E0B4, int, (int, u32))(right, 0x00100000))
                add_row(state, right | (right << 8), index, right, right, name, 0);
        }
    }
    for (int row = 0; row < state->count; row++) {
        if (state->rows[row].identity == state->identity) { state->selected = row; return; }
    }
    if (state->selected >= state->count) state->selected = state->count - 1;
    if (state->selected < 0) state->selected = 0;
    if (state->count) state->identity = state->rows[state->selected].identity;
}

__attribute__((section(".input")))
u32 quick_select_input(u32 buttons, u32 oldbuttons, Selector *state) {
    /* 1. Suspend outside live play and bound native memory before walking it. */
    u32 player = WORD(0x8007A0B0);
    if (!active(player) || player != state->player || WORD(player + 0x11E4) != state->pool
        || !validate_inventory(player) || (buttons & 0x1000)) {
        state->open = 0; state->released = 0; state->previous_buttons = buttons;
        return 0;
    }
    state->updates++;
    u32 edges = buttons & ~state->previous_buttons;
    state->previous_buttons = buttons;
    if (!(buttons & 0x0F00)) state->released = 1;
    if (!state->released) return 0x0F00;
    int ticks = WORD(0x80048374);
    int direction = (buttons & 0x0800) ? -1 : (buttons & 0x0400) ? 1 : 0;
    if ((buttons & 0x0C00) == 0x0C00) direction = 0;

    /* 2. Reconcile by identity, then move a fixed highlight through native rows. */
    if (!state->open) {
        if (!(edges & 0x0C00)) return 0x0F00;
        state->open = 1; state->idle_ticks = 0; state->repeat_ticks = 21;
        state->direction = direction;
        if (!state->identity && !state->category)
            state->identity = CALL(0x7F05D434, int, (int, int))(0, 0)
                | (CALL(0x7F05D434, int, (int, int))(1, 0) << 8);
        read_entries(state);
        return 0x0F00;
    }
    if (edges & 0x0200) {
        state->category ^= 1; state->selected = 0; state->identity = 0;
    }
    read_entries(state);
    int step = 0;
    if (!direction) { state->direction = 0; state->repeat_ticks = 21; }
    else if (direction != state->direction || (edges & 0x0C00)) {
        step = direction; state->direction = direction; state->repeat_ticks = 21;
    } else {
        state->repeat_ticks -= ticks;
        if (state->repeat_ticks <= 0) { step = direction; state->repeat_ticks = 7; }
    }
    if (step && state->count) {
        state->selected = (state->selected + step + state->count) % state->count;
        state->identity = state->rows[state->selected].identity;
    }
    state->idle_ticks = (buttons & 0x0F00) ? 0 : state->idle_ticks + ticks;
    if (state->idle_ticks >= 180) state->open = 0;

    /* 3. Request each hand's native pending transition once, only on Right. */
    if ((edges & 0x0100) && state->count) {
        Row *row = &state->rows[state->selected];
        if (!row->passive && usable(player, row->right)) {
            CALL(0x7F05D4E0, void, (int, int, int))(0, row->right, 0);
            CALL(0x7F05D4E0, void, (int, int, int))(1, row->left, 0);
            state->last_right = row->right; state->last_left = row->left;
            state->selections++; state->open = 0;
        }
    }
    return 0x0F00;
}

INLINE u32 *draw_text(u32 *display, int x, int y, char *text, u32 colour, int right_edge, int *height) {
    char clean[96];
    char wrapped[192];
    int start_y = y;
    int length = 0;
    if (!text) return display;
    while (length < 95 && text[length] && text[length] != '\n') { clean[length] = text[length]; length++; }
    clean[length] = 0;
    /* Only the highlighted name wraps; neighbouring rows are one-line previews. */
    if (height) CALL(0x7F0AEB64, void, (int, char *, char *, u32, u32))
        (right_edge - x, clean, wrapped, WORD(0x80040EB0), WORD(0x80040EAC));
    display = CALL(0x7F0ADABC, u32 *, (u32 *, int *, int *, char *, u32, u32, u32, short, short, int, int))
        (display, &x, &y, height ? wrapped : clean, WORD(0x80040EB0), WORD(0x80040EAC), colour, right_edge, 240, 0, 11);
    if (height) *height = y - start_y + 11;
    return display;
}

__attribute__((section(".render")))
u32 *quick_select_render(u32 *display, Selector *state) {
    /* 4. Append native text; inventory and equipment are never changed here. */
    if (!state->open || !active(state->player) || WORD(0x8007A0B0) != state->player) return display;
    int left = CALL(0x70004514, int, (void))() + 8;
    int right = left + 112;
    /* Match the native dialogue origin and leave three full lines above the list. */
    int view_top = CALL(0x70004524, int, (void))();
    int dialogue_top = view_top + 13;
    if (WORD(0x8003642C)) dialogue_top = ((view_top + 32) / 11) * 11 - 2;
    u32 dialogue_font = WORD(0x80040EB8);
    int dialogue_line_height = WORD(dialogue_font + 0x88C) + WORD(dialogue_font + 0x890);
    int top = dialogue_top + 3 * dialogue_line_height + 6;
    int bottom = top + 88;
    display = CALL(0x7F0ACD98, u32 *, (u32 *))(display);
    display = CALL(0x7F0ACF4C, u32 *, (u32 *, int *, int *, int *, int *))(display, &left, &top, &right, &bottom);
    display = draw_text(display, left + 7, top + 5, state->category ? TEXT(32) : TEXT(0), 0xD4C58AFF, right, 0);
    if (!state->count) display = draw_text(display, left + 14, top + 33, TEXT(64), 0xB8B8B8FF, right, 0);
    int selected_height = 11;
    for (int relative = -1; relative <= 1 && state->count; relative++) {
        int index = state->selected + relative;
        if (index < 0 || index >= state->count) continue;
        Row *row = &state->rows[index];
        int y = top + (relative < 0 ? 21 : relative == 0 ? 33 : 35 + selected_height);
        if (!relative) display = draw_text(display, left + 5, y, TEXT(80), 0xFFFFFFFF, right, 0);
        display = draw_text(display, left + 14, y, row->name, relative ? 0x8F9C9FFF : 0xFFFFFFFF, right - 4,
                            relative ? 0 : &selected_height);
    }
    char *footer = TEXT(112);
    if (state->count && state->rows[state->selected].passive) footer = TEXT(144);
    else if (state->count && state->rows[state->selected].left) footer = TEXT(176);
    display = draw_text(display, left + 7, top + 49 + selected_height, footer, 0xD4C58AFF, right, 0);
    return CALL(0x7F0ACEF0, u32 *, (u32 *))(display);
}
