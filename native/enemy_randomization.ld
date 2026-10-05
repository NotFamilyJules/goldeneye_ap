SECTIONS {
    . = 0x8007F400;
    .text : { *(.text*) }
    .rodata : { *(.rodata*) }
    ASSERT(. <= 0x8007F700, "Enemy code overlaps audio helper")
    . = 0x8007F700;
    .audio : { *(.audio) }
    /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) }
    ASSERT(. <= 0x8007F800, "Native payload exceeds loader size")
}
