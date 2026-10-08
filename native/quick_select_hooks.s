.set noreorder
.set noat
.include "quick_select_offsets.inc"
.text
.globl quick_select_init_hook, quick_select_input_hook, quick_select_render_hook

# 1. Preserve native inventory allocation, then allocate this mission's selector.
quick_select_init_hook:
    addiu $sp,$sp,-32
    sw $ra,28($sp)
    jal original_init
    nop
    lui $t0,0x8008
    sw $zero,-0xA0($t0)
    lui $t9,0x7000
    ori $t9,$t9,0x9720
    addiu $a0,$zero,0x3000
    jalr $t9
    addiu $a1,$zero,4
    beq $v0,$zero,init_return
    nop
    lui $t0,0x8008
    sw $v0,-0xA0($t0)
    lui $t1,0xb0c0
    addiu $t1,$t1,-0x4000
    move $t2,$v0
    addiu $t3,$v0,0x2000
copy_code:
    lw $t4,0($t1)
    sw $t4,0($t2)
    addiu $t1,$t1,4
    addiu $t2,$t2,4
    bne $t2,$t3,copy_code
    nop
    addiu $t5,$v0,0x3000
clear_state:
    sw $zero,0($t2)
    addiu $t2,$t2,4
    bne $t2,$t5,clear_state
    nop
    lw $t4,-0x5F50($t0)
    sw $t4,-0x9C($t0)
    sw $t4,0($t3)
    lw $t4,0x11E4($t4)
    sw $t4,-0x98($t0)
    sw $t4,4($t3)
    move $t2,$v0
flush_code:
    cache 0x19,0($t2)
    sync
    cache 0x10,0($t2)
    addiu $t2,$t2,16
    bne $t2,$t3,flush_code
    nop
init_return:
    lw $ra,28($sp)
    jr $ra
    addiu $sp,$sp,32

original_init:
    lui $v0,0x8008
    addiu $v0,$v0,-0x5F50
    lw $t7,0($v0)
    addiu $sp,$sp,-24
    lui $t9,0x7f00
    ori $t9,$t9,0x626C
    jr $t9
    nop

# 2. Read raw directions; filter only the arguments consumed by player movement.
quick_select_input_hook:
    addiu $sp,$sp,-40
    sw $ra,36($sp)
    sw $a0,16($sp)
    sw $a1,20($sp)
    sw $a2,24($sp)
    sw $a3,28($sp)
    jal live_payload
    nop
    move $t9,$v0
    beq $t9,$zero,input_restore
    move $v0,$zero
    move $a0,$a2
    move $a1,$a3
    addiu $a2,$t9,0x2000
    addiu $t9,$t9,QUICK_INPUT
    jalr $t9
    nop
input_restore:
    lw $a0,16($sp)
    lw $a1,20($sp)
    lw $a2,24($sp)
    lw $a3,28($sp)
    nor $v0,$v0,$zero
    and $a2,$a2,$v0
    and $a3,$a3,$v0
    lw $ra,36($sp)
    addiu $sp,$sp,40
    # Displaced native input prologue, unchanged.
    addiu $sp,$sp,-448
    sdc1 $f20,48($sp)
    mtc1 $zero,$f20
    sw $ra,60($sp)
    lui $t9,0x7f08
    ori $t9,$t9,0x1984
    jr $t9
    nop

# 3. Keep native HUD drawing, then append the selector's display-list commands.
quick_select_render_hook:
    addiu $sp,$sp,-32
    sw $ra,28($sp)
    jal original_render
    nop
    sw $v0,16($sp)
    jal live_payload
    nop
    move $t9,$v0
    lw $v0,16($sp)
    beq $t9,$zero,render_return
    move $a0,$v0
    addiu $a1,$t9,0x2000
    addiu $t9,$t9,QUICK_RENDER
    jalr $t9
    nop
render_return:
    lw $ra,28($sp)
    jr $ra
    addiu $sp,$sp,32
original_render:
    lui $v0,0x8008
    lw $v0,-0x5F50($v0)
    addiu $sp,$sp,-96
    sw $ra,52($sp)
    lui $t9,0x7f08
    ori $t9,$t9,0xA60C
    jr $t9
    nop

# The stage bank is reused by menus. Never enter expired stage code to ask whether it is live.
live_payload:
    move $v0,$zero
    lui $t0,0x8003
    lw $t1,-0x5740($t0)
    addiu $t2,$zero,11
    bne $t1,$t2,payload_return
    nop
    lui $t0,0x8008
    lw $t1,-0x5F50($t0)
    lw $t2,-0x9C($t0)
    beq $t1,$zero,payload_return
    nop
    bne $t1,$t2,payload_return
    nop
    lw $t1,0x11E4($t1)
    lw $t2,-0x98($t0)
    bne $t1,$t2,payload_return
    nop
    lw $v0,-0xA0($t0)
payload_return:
    jr $ra
    nop
