.set noreorder
.set noat
.text
.globl surface_mine_preload, surface_mine_create

# 1. Set only gadget 47's held model header and file during native stage loading.
# Other stages restore the original Bug pointers. Stats, ammo and names stay intact.
surface_mine_preload:
    lui $t0,0x8002
    lw $t0,0x41A8($t0)
    addiu $t1,$zero,43
    lui $t2,0x8003
    bne $t0,$t1,restore_bug
    nop
    lw $t0,0x3F7C($t2)
    lw $t1,0x3F80($t2)
    sw $t0,0x436C($t2)
    sw $t1,0x4370($t2)
    addiu $t0,$zero,47
    bne $a0,$t0,preload_original
    nop
    addiu $a0,$zero,29
    b preload_original
    nop
restore_bug:
    lui $t0,0x8004
    addiu $t0,$t0,-0x3140
    lui $t1,0x8005
    addiu $t1,$t1,0x39C8
    sw $t0,0x436C($t2)
    sw $t1,0x4370($t2)
# 2. Load the matching world model before the gadget can be thrown.
preload_original:
    addiu $t6,$a0,-3
    addiu $sp,$sp,-24
    sltiu $at,$t6,46
    sw $ra,20($sp)
    lui $t9,0x7F00
    ori $t9,$t9,0x5720
    jr $t9
    nop

# 3. Keep weapon ID 47 on the placed object. Only its model becomes a mine.
surface_mine_create:
    addiu $t0,$zero,47
    bne $a1,$t0,create_original
    nop
    lui $t0,0x8002
    lw $t0,0x41A8($t0)
    addiu $t1,$zero,43
    bne $t0,$t1,create_original
    nop
    addiu $a0,$zero,199
create_original:
    sll $t6,$a0,2
    addiu $sp,$sp,-184
    subu $t6,$t6,$a0
    sll $t6,$t6,2
    lui $t9,0x7F05
    ori $t9,$t9,0x207C
    jr $t9
    nop
