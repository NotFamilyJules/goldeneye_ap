# GoldenEye 007 AP World

I wanted to play GoldenEye in Archipelago and no one else did it so here we are. This is `v0.2` of the Goldeneye 007 Archipelago World.

Also yes hi, despite the username, yes I am the music guy (FamilyJules was taken). I decided music wasn't frusturating enough so I decided to make like a millenial and "learn to code". I'm still baby so please be gentle.

# WHAT Is Random?

- Mission Unlocks.
- Starting Level
- Weapons (either progressively by damage or individually)
- Mission Gadgets (like Covert Modem, Watch Laser, etc.)
- Key Items (Keycards, Keykeys, and other mission specific keys)
- Tanks
- Cheats (Cheats can be sent to you and activate mid level, but items will be at cheat unlocks)
- Enemy and Bond Models (optional)
- Enemy Weapon Loadouts (optional and VERY difficult)
- Music and Sound Effects (also optional, but come on...)

Progressive Weapons is generally in order of how much damage the weapon does and only rearranged for feasibility in all scenarios (like Grenade Launchers are great for streets, not so much train) and importantly, the Golden Gun, is moved back so that even in the least locations selected possible, you can still logically complete Egyptian.

# WHERE is Random?

- Objectives
- Mission Clears
- Item Pickups (keys, documents, etc.)
- Freestanding Weapons (Dam Sniper Rifle, Archives PP7, etc.)
- NPC Handoffs (Doak's Door Decoder, Mishkin's Safe Key)
- Body Armor (Optional, but armor can show up in some difficulties and not in others)
- Ammo Crates (The green and tan that usually have mines or ammo, there's not as many in the game as you may think)
- Cheat Unlock Challenges (Cheats are unlocked by beating levels under the target time on a specific difficulty, now that can send a check)

Options allow for either "per difficulty" which means each objective in each difficulty is a check (normal) or "shared" you only need to get the objective once across all difficulties (for babies).

Mission clears works the same, either one check per level no matter the difficulty or each difficulty clear is a check. I won't judge you on what you choose, I'm not that kind of guy.

Item Shuffler is on by default which includes Freestanding Items, NPC Drops, and NPC Handoff. Items are level specific so they will unlock for you when you enter the level they're used in. In many cases, getting the item is an objective so you'll get the objective completed immediately at level start if that's the case. 

Since there's a lot of key items to keep track of, I've made a bare bones tracker of the level objects you own on the map select screen so you can see what you can do. VincentSin is working on a more in depth PopTracker so keep an eye out on the Goldneye Archipelago Discord Channel in #future-game-design. I'll have the latest PopTracker pinned when available.

Body Armor and Ammo Crate shuffler is off by default but it was really hard to implement so please at least try it. Remember that body armor does not appear in every difficulty, but all the body armor available to a level is available in Agent difficulty. It incentivizes not always going in 00 Agent for the objectives.

Cheats are off by default, but it's very fun. Having cheats on does NOT stop you from clearing the level, accomplishing objectives for checks, or even stop you from getting other cheats. The trade off I figured is yes you get over powered, BUT you have to look for checks by doing the particular speedrun that would normally get you a cheat. 

# HOW is Random?

Thanks to the full decomp of Goldeneye, I've been able to unearth all the memory addresses I needed to fulfill my dream of this game and compared to the v0.1, this really feels like a true Archipelago game with Item Shuffler now. Still, a ton of absolute fuckery ensued in making this work, especially by making way too much use of the unused token item in memory to get around the absolute glasslike fragility of Goldeneye's code. You may notice some interesting texture glitches while sweeping through items in the menu, and that's because many of the items aren't real and are being transformed from the token into another model to give the impression you have it while I'm giving you the effect of the item artificially. The reason for this is that I found out early on that a key item cannot exist in two places at once, or else the game crashes. Typically you'd have the vanilla item in an AP be at the location and just deny it from entering inventory at acquisition, but in GE if that item exists in your inventory because you have it, and is on a guard, the game get's very confused and opts to crash instantly. This was my most robust way around it.

As this is my first big coding project ever, I've found myself in the unfortunate position of hitting hard walls and having to rely on AI to get through some. The first version ended up being so vibe-coded that everything I did was further breaking the build so I opted to flesh code the entire thing from scratch this time around, learning a very valuable lesson that I think I already knew but suffered it's fate anyway. While AI was used as a consultant on many features of this, not a single line of code was copied and even when it gave me code despire me telling it not to, I wrote it myself and made sure I understood every step, hence the endless vulgar comments.

In my opinion, the biggest feature of this AP implementation has to be credited to Murk17 who shortly after GE was 100% decomped, released an absolutely amazing randomizer of models, loadouts, and music called Random-eye-zer. It's absolutely amazing and you should try it out for yourself. I tried very hard to find a way to reach him them but ultimately came up short, so I ran some diffs on the patched rom hack and the vanilla to find what they were doing. All of the methods of randomizing those things have to be directly credited to them. SFX was more of my own work and I spent an insane amount of time organizing them for catagorizing if you want to randomize them, but don't want the absolute chaos that is true random sfx.

# WHY is Random?

Goldeneye is one of my absolute cherished games growing up, and I hope this implementation gives you another reason to play through one of my favorite games again for even longer!

# What else did you add or change?

The biggest new change that I haven't talked about is QUICK EQUIP! Using the d-pad you can now scroll through your weapons in-game to find the one you're looking for WITHOUT PAUSE. D-pad right will equip the one you have seleceted and d-pad left will switch to gadgets so you don't have to press pause and scroll forever just to take out the cover modem or goldeneye key once. This was one of the biggest quality of life things I wanted but didn't know if it was possible. Hopefully you guys like it!

You now can choose not to pick up a guards weapon, which is the intended rule for this randomizer. I'd like you to only be stuck with your loadout weapons that you've unlocked through AP, but to make it a bit more fair you can choose to have enemy weapon pickups give you ammo. That's the way I've been playing it.

Dialog replacement is easier than ever, just open up patch_rom.py, copy the template towards the bottom and you can change anyone's vanilla line of dialog to whatever you want. I'll definitely have some more in the future, but I really wanted to streamline it moving forward.

Again, the map select screen will show which items you have unlocked for loadout of that level, but if that's annoying to look at, simply press F8 and it'll go away.

# Roadmap for v0.3

- Custom Models and Markers - I've proven simple model skin changes, but I would really like to make an archipelago logo on items you have not yet got the check for, as well as find someway to signify which NPC has an item you haven't gotten the check for. Think maybe like a sims diamond over their head or something idk.
- Cock Shot Sanity - I've been struggling with too many items and not enough locations for this AP, so shout-outs to Puffles for suggesting adding a number of times shooting someone in the dick sends a check. Haven't proved it, but it can't be that hard.
- PC Port implementation - I worked very hard to isolate the majority of the moving parts to a python script so that if/when a PC Port is released, this AP will not need TOO too much work to get working with it.
- Mouse Support - A few people got the first implementation working with the 1964 emulator so they can use Mouse Aiming and I think that's really cool. Technically it might even be possible with bizhawk but, fuck that. Again, hoping for a PC Port soon!
- Quality of Life Improvements - I'd like to implement more on the quick select and allow you to set a favorite weapon to always start a level with to cut down on the endless A mash scrolling through weapons.
- More locations - I spent a good amount of time doing dumb shit like making Boris' PP7 or the AR33 Easter Egg in Caverns a check and I really want to find interesting ways to make more locations. All I can think of is doing something truly abhorrent and making like wooden crate sanity or something. There's no way I'm mapping all those out, but if you're bored enough, have at it, I'll put it in just to see the world burn.
- Lag reduction - the game CHUGS sometimes and it loads incredily slow. I really wanna find some ways to cut down on those things where I can, but a PC Port will probably handle that just fine so I'll be patient.

# Special Thanks

Vincent'sSin for compiling every item in the game and logic for them and then for letting me use it for this AP. It's going to be invaluable for moving forward with the checks in the future.

kholdfuzion for his intense and extensive research for the Goldeneye Decomp project and for sharing. This would not be possible without his findings and documentation of hex addresses.

Murk17 for making the amazing Random-eye-zer that I used as reference and borrowing for the same implementations for this.

PixelShake92 for helping me find addresses and sharing his extensive wisdom with me on creating an apworld. Super special thanks to him for his patience with all the dumb questions I asked you and time I took away from you releasing the Banjo-Kazooie AP.

# Included in the release:
- the Archipelago world implementation
- goldeneye_ap_randomizer.lua
- the unlock everything rom patch
- player setup documentation in `docs/setup_en.md`

Disclaimer: As I am a budding young bushy eyed developer, AI was partially used to create this APWorld. I despise AI, but in the process of learning how to make apworlds, I've mostly used it as a guardrail professor to slap me with a ruler anytime I do anything wrong and explain to me why I'm dumb and should give up. The ultimate goal for me is to rewrite the code when it's working completely from scratch to make sure no AI was used in the full release of this apworld. I don't condone using AI to make apworlds, mostly because of it's effects on the world, but also because it's really stupid and most of the time can't do anything right unless you already know what you're doing anyway and can do it without.

Thank you so much for helping me with creating this apworld. My dream for a long time has been to make these for games I love and it's very exciting to me that that is becoming a reality!

Happy hunting, 007.

## AP item messages

`GoldeneyeClient.py` contains the whole message feature:
`AP_MESSAGE_TEMPLATES` controls wording, `format_ap_message` handles wrapping,
`queue_ap_message` selects transfers involving this slot, and `show_ap_message`
adds one message to the native bottom-left HUD queue.

Messages read "{item} received from {player}" or "{item} sent to {player}".
A self-found item produces one received message. Item names use the recipient's
game data, so outgoing items from other games are named correctly.
The feed uses live server ItemSend events, not chat parsing, item grants, or
replayed ReceivedItems history. Hints, cheats and transfers between other slots
are not displayed. Reconnecting does not replay old events. Transfers received
while in menus or with the HUD hidden wait in Python until live gameplay.

The existing guarded transport commits one unused native queue slot and its
count together. Pickup/objective text gets to finish first. Native code controls
rendering and display duration. Production Lua and the ROM are unchanged.
Messages wrap at 28 characters and two lines per page; long names continue on
following pages instead of being truncated. USA ASCII is used; unsupported
characters become question marks after Unicode normalization.

After editing this feature, repackage/install the AP world and restart the AP
client. No ROM rebuild or new seed is needed for these Python message changes.
Tests: `python -m unittest test_ap_messages test_deathlink_traps test_playthrough_fixes`
from `test_build`. `ap_message_live_test.py` uses an isolated two-player AP room,
server-issued location checks, the existing Dam startup route, and read-only
native HUD observations/screenshots.

## Completed mission labels

AP-confirmed mission clears turn the mission-select film label green. Only the
latest newly confirmed mission clear uses `YOUR` / `DID IT` on two lines for
one mission-select visit. Leaving that screen restores the normal green name
on all later visits. The client saves a pending message per seed, team and slot
until it is successfully published on mission select, then consumes it so a
client restart cannot replay it. Existing progress stays green under its normal
names until a new clear arrives. A batch confirming
multiple missions does not invent an order. Any confirmed difficulty counts when
mission clears are separate. Objective checks and unconfirmed local clears do
not count. Other labels and internal mission/AP names are unchanged.

Edit `CLEARED_MISSION_LABEL` in GoldeneyeClient.py to change the wording. It uses
ASCII and optional `\n` line breaks, at most 22 bytes plus the native newline
and terminator in a 24-byte buffer. Film-frame width also matters; keep each
line short. The native menu uppercases the label.

The initial feature needs a newly rebuilt ROM and updated AP client. Later
wording edits only require repackaging/installing the client and restarting it.
Lua is unchanged. `completed_menu_live_test.py` verifies consecutive server-confirmed
Dam and Facility clears, the older green Dam name, and menu reload in an isolated
AP room.

## ROM text replacement compression

`patch_text_replacements` in `patch_rom.py` uses Zopfli 0.4.3 with 15 iterations
to fit more edits into the original compressed bank allocation. Install the
build dependency with `python -m pip install zopfli==0.4.3`. Zlib still handles
decompression. Zopfli is only required when building ROM patches, not when
playing or applying the prebuilt `.apge`.

Replacement text must still fit the original string allocation, and the
compressed bank must still fit its original ROM allocation. No offsets or
following files move. Rebuild through `test_build/build_rom.py --install`, then
generate fresh `.apge` output. Existing `.apge` files keep their embedded patch.
