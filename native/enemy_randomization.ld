SECTIONS {
    . = 0x8007F400;
    .text : { *(.text*) }
    .rodata : { *(.rodata*) }
    ASSERT(. <= 0x8007F700, "Enemy code overlaps audio helper")
    . = 0x8007F700;
    .audio : { *(.audio) }
    ASSERT(. <= 0x8007F740, "Sound hook overlaps music hook")
    . = 0x8007F740;
    .music : { *(.music) }
    ASSERT(. <= 0x8007F780, "Music hook overlaps Bond hook")
    . = 0x8007F780;
    .bond : { *(.bond) }
    ASSERT(. <= 0x8007F800, "Bond hook overlaps allocation helper")
    . = 0x8007F800;
    .bond_support : { *(.bond_support_hooks) *(.bond_support) }
    /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) }
    ASSERT(. <= 0x8007FA00, "Native payload exceeds loader size")
}
