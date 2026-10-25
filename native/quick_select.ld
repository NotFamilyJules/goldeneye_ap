SECTIONS {
    . = 0;
    .text : { *(.input) *(.render) *(.text*) }
    .rodata : { *(.rodata*) }
    /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.comment) *(.gnu.attributes) }
    ASSERT(. <= 0x2000, "Quick-select code exceeds its stage allocation")
}
