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
.globl all_sfx
all_sfx:
    # snd.c's internal replay already contains the selected ID.
    lui $t0,0x7001
    addiu $t0,$t0,-0x7738
    beq $ra,$t0,audio_original
    sltiu $t0,$a1,262
    beq $t0,$zero,audio_original
    sll $t0,$a1,2
    lui $t1,0xb0c0
    addiu $t1,$t1,-0x1800
    addu $t1,$t1,$t0
    lw $a1,0($t1)
audio_original:
    # Displaced prologue of sndPlaySfx. Preserve bank, handle and return PC.
    addiu $sp,$sp,-128
    lui $t7,0x8002
    lui $t9,0x7000
    ori $t9,$t9,0x8e10
    jr $t9
    nop

.section .music,"ax",@progbits
.globl frontend_music
frontend_music:
    sll $t0,$a0,2
    lui $t1,0xb0c0
    addiu $t1,$t1,-0x1300
    addu $t1,$t1,$t0
    lw $a0,0($t1)
    lui $t9,0x7000
    ori $t9,$t9,0x6e7c
    jr $t9
    nop

.section .bond,"ax",@progbits
.globl bond_appearance
bond_appearance:
    addiu $sp,$sp,-32
    sw $ra,28($sp)
    lui $t9,0x7f09
    ori $t9,$t9,0xa464
    jalr $t9
    nop
    addiu $t0,$zero,1
    bne $v0,$t0,bond_return
    nop
    lui $t9,0x7000
    ori $t9,$t9,0xa450
    jalr $t9
    nop
    lui $t0,0x8008
    lw $t0,-0x5f50($t0)
    andi $v0,$v0,7
    sw $v0,0x41c($t0)
    jal choose_appearance
    nop
    srl $t0,$v0,16
    sll $t1,$v0,16
    sra $t1,$t1,16
    sw $t0,0x64($sp)
    sw $t1,0x60($sp)
    addiu $v0,$zero,1
bond_return:
    lw $ra,28($sp)
    jr $ra
    addiu $sp,$sp,32

.section .bond_support_hooks,"ax",@progbits
.globl bond_head_allocation
bond_head_allocation:
    addiu $sp,$sp,-32
    sw $ra,28($sp)
    or $a1,$a0,$zero
    jal prepare_bond_body
    addiu $a0,$sp,32
    lw $t0,0x60($sp)
    lw $ra,28($sp)
    bgez $t0,bond_head_original
    addiu $sp,$sp,32
    lui $t9,0x7f07
    ori $t9,$t9,0xa234
    jr $t9
    or $a3,$zero,$zero
bond_head_original:
    jr $ra
    nop
