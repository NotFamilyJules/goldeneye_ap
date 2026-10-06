# GoldenEye 007 Setup Guide

## First-time setup

Install Archipelago 0.6.7 or newer, BizHawk 2.10, and the matching
`goldeneye.apworld`. Restart Archipelago after installing the world.
You need your own original USA GoldenEye 007 ROM in `.z64` format.
An already patched ROM will not work as the base.

## Play from a room

1. Download your player's `.apge` patch from the Archipelago room page.
2. Open it with Archipelago Launcher. On Windows, use **Open with**, select
   `ArchipelagoLauncher.exe`, and choose to always use it for `.apge` files.
   Alternatively, use **Open Patch** in Archipelago Launcher.
3. On first use, select your base ROM and `EmuHawk.exe` when asked.

The launcher creates a patched `.z64` beside the download, starts BizHawk,
loads GoldenEye's Lua script, enables the 8 MiB Expansion Pak, and opens the
client. The ROM supplies your slot and seed. Room downloads supply the server
address. A password-protected room still asks for its password.

For a patch taken directly from a locally generated output ZIP, enter the
server address in the client. That file has not yet received a hosted room's
connection address.

The launcher keeps a separate GoldenEye BizHawk profile under Archipelago's
user folder at `goldeneye/bizhawk`. It initially copies your normal BizHawk
controls and preserves changes you make in that profile. The original
BizHawk configuration is not changed. Launch from a cold boot, not an old
save state. Close an earlier GoldenEye emulator/client before opening another
room patch.

## Generate a seed

Configure your GoldenEye player YAML and generate normally. The output ZIP
now includes a separate `.apge` for each GoldenEye player. Upload the generated
game to a room or distribute those patches to players. The seed host does not
need a base ROM; only players need one when applying their patches.

Appearances, enemy loadouts, music, and SFX randomization default off.
Appearances includes Bond's model and cuffs. Music includes intro and menus.
Set `sfx_randomization` to `weapons_only`, `catagories`, `true_random`, or `off`.
Weapons Only includes attacks, slappers, throws, reloads, clicks and equip sounds.
Categories separates gunfire/explosions/impacts, voices, ricochets/flybys,
casings, machinery/ambience, and electronics/interface. Equip, reloads and
clicks join electronics/interface. True Random shuffles all sound effects.
Continuous sounds keep their stop behavior. The ROM requires the 8 MiB Expansion Pak.

Generate a new room with the updated world to use these changes. Its `.apge`
contains the sound map and intro/menu music choices, so those work before the
client connects. Existing room downloads keep their earlier patch and options.
Full mission testing, comprehensive music transitions, and normal-playthrough
victory confirmation remain unfinished. See [randomization details](randomization.txt).

## Manual play

Use the ROM produced from your room's `.apge` with the BizHawk Client and
`goldeneye_ap.lua`. The generic build ROM has no slot-specific audio shuffle.
Manual setup requires enabling the Expansion Pak, loading
the Lua script, and entering the server and slot yourself. Use the ROM,
client, and Lua from the same build.

Set `skip_cutscenes: true` before generating to skip mission openings. This
does not skip endings, deaths, dialogue, or objective scenes. Received cheat
items unlock native menu entries; choose them before starting a mission.
Cheat-unlock checks require successful runs with cheats off.

## Building the world package

After changing the ROM patcher or its native payload, run
`python test_build/build_room_patch.py` before packaging the world. This build
step requires `bsdiff4` and the original USA ROM. It regenerates the bundled
ROM delta and verifies that applying it reproduces the main build. No ROM
is included in the `.apworld` or room download.
