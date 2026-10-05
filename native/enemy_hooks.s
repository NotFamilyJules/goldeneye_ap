.set noreorder
.set noat
.text
.globl setup_appearance, dynamic_appearance, setup_weapon, scripted_weapon

# Original caller locals must match the model arguments after substitution.
.macro appearance name, body_slot, head_slot
\name:
    addiu $sp,$sp,-32
    sw $ra,28($sp)
    sw $a2,24($sp)
    jal choose_appearance
    nop
    lw $a2,24($sp)
    lw $ra,28($sp)
    addiu $sp,$sp,32
    srl $a0,$v0,16
    sll $a1,$v0,16
    sra $a1,$a1,16
    sw $a0,\body_slot($sp)
    sw $a1,\head_slot($sp)
    lui $t9,0x7f02
    ori $t9,$t9,0x34d0
    jr $t9
    nop
.endm
appearance setup_appearance,0x34,0x30
appearance dynamic_appearance,0x40,0x44

# RNG clobbers argument registers. Preserve all native arguments and RA.
.macro save_arguments
    addiu $sp,$sp,-40
    sw $ra,36($sp)
    sw $a0,16($sp)
    sw $a1,20($sp)
    sw $a2,24($sp)
    sw $a3,28($sp)
.endm
.macro restore_arguments
    lw $a0,16($sp)
    lw $a1,20($sp)
    lw $a2,24($sp)
    lw $a3,28($sp)
    lw $ra,36($sp)
    addiu $sp,$sp,40
.endm
setup_weapon:
    save_arguments
    jal choose_weapon
    nop
    restore_arguments
    beq $v0,$zero,1f
    srl $t0,$v0,8
    andi $a0,$v0,255
    sh $t0,4($a3)
    sb $a0,0x80($a3)
    addiu $t0,$zero,256
    sh $t0,0($a3)
1:  lui $t9,0x7f00
    ori $t9,$t9,0x5710
    jr $t9
    nop

scripted_weapon:
    save_arguments
    jal choose_weapon
    or $a0,$a2,$zero
    restore_arguments
    beq $v0,$zero,2f
    nop
    srl $a1,$v0,8
    andi $a2,$v0,255
2:  lui $t9,0x7f05
    ori $t9,$t9,0x2214
    jr $t9
    nop

.section .audio,"ax",@progbits
.globl death_sfx
death_sfx:
    lw $t0,0x18($a3)
    lbu $t0,0($t0)
    addiu $t1,$zero,6
    beq $t0,$t1,audio_original
    nop
    lwc1 $f4,0xfc($a3)
    lwc1 $f6,0x100($a3)
    c.le.s $f6,$f4
    bc1f audio_original
    nop
    addiu $t0,$a1,-0x86
    sltiu $t1,$t0,25
    bne $t1,$zero,audio_lookup
    nop
    addiu $t0,$a1,-13
    sltiu $t1,$t0,2
    beq $t1,$zero,audio_original
    nop
    addiu $t0,$t0,25
audio_lookup:
    sll $t0,$t0,1
    lui $t1,0x8008
    addiu $t1,$t1,-0xce0
    addu $t1,$t1,$t0
    lhu $a1,0($t1)
audio_original:
    lui $t9,0x7000
    ori $t9,$t9,0x8e08
    jr $t9
    nop
