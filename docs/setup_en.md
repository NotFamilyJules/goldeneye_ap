# GoldenEye 007 Setup Guide

## What You Need

- Archipelago `0.6.6` or newer
- BizHawk (Tested on 2.10, let me know if it works on other versions)
- GoldenEye 007 .apworld
- goldeneye_ap_randomizer.lua
- GoldenEye 007 ROM that you definitely legally acquired
- "GoldenEye 007 (U) [!] Everything Unlocked.bps"

## Install the AP World

1. Once Archipelago is installed, double click goldeneye.apworld and wait for the pop-up to say it installed successfully.
2. Restart Archipelago tools if they were already open. I still mess this up all the time, you actually have to completely close everything AP if you install a new apworld.

## Generate a Seed

1. Open your YAML template.
2. Configure your GoldenEye options.
3. Generate normally through Archipelago.
4. Do death_link unless you're a big baby.

## Patch your legally acquired GoldenEye ROM

1. I'll definitely have this done for you in a later build but...
2. https://www.marcrobledo.com/RomPatcher.js/ unless you have a better way of patching.
3. ROM file is the vanilla rom. Patch file is the "GoldenEye 007 (U) [!] Everything Unlocked.bps".
3. Apply Patch.
4. That shooould be it.

## Connect to Archipelago

1. Open Archipelago Launcher.
2. Search or scroll to find BizHawk Client.
3. Double click it until it actually opens.
4. Connect it to your server using the top bar.
5. It's going to wait until the lua is loaded in the next step. After that it'll prompt for your SLOT NAME.

## BizHawk Setup

IMPORTANT: Make sure you've put goldeneye_ap_randomizer.lua in C:\ProgramData\Archipelago\data\lua. It needs to be in the same folder as `connector_bizhawk_generic.lua`.

1. Open the patched GoldenEye ROM in BizHawk.
2. Tools > Lua Console
3. Script > Open Script...
4. Load `goldeneye_ap_randomizer.lua`.

## BizHawk Setup

1. Open the patched GoldenEye ROM in BizHawk.
2. Tools > Lua Console
3. Script > Open Script...
2. Load `goldeneye_ap_randomizer.lua`.

## Troubleshooting

- If the client does not connect, make sure `goldeneye_ap_randomizer.lua` and `connector_bizhawk_generic.lua` are in the same folder.
- If the world does not appear in Archipelago, confirm the `.apworld` is in `custom_worlds` and that `archipelago.json` is present inside the package.
