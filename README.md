# GoldenEye 007 AP World

I wanted to play GoldenEye in Archipelago and no one else did it so here we are. This is `v0.0.1` of the Goldeneye 007 Archipelago World.

Also yes hi, despite the username, yes I am the music guy (FamilyJules was taken). I decided music wasn't frusturating enough so I decided to make like a millenial and "learn to code". I'm still baby so please be gentle.

# So what is randomized, anyway?

- All your level unlocks.
- All your guns.

For now that's the item list we've got here. Read below in roadmap for what the plans are. The current options allow for either all guns to be items in the pool, or progressive weapons which will unlock in order of how good they are based on my super correct opinions. Feel free to debate me on changes you'd make in a multiplayer game with me where you get the better weapon and I get the next one down.

# So where do I get checks, anyway?

- Objectives
- Level Clears

Options allow for either per difficulty which means each objective in each difficulty is a check (normal) or you only need to get the objective once across all difficulties (for babies).

Level clears works the same, either one check per level no matter the difficulty or each difficulty clear is a check. I won't judge you on what you choose, I'm not that kind of guy.

# What else did you add or change?

You'll notice at the start of every level, Bond might take out his gun but then forget he's not supposed to have it because you're limitied to your AP Loadout. He will still use it to beat people over the head. I compromised with him on that one. 

You will keep your usual mission gadgets loadout... for now.
You can also pick up enemy weapons... for now.

There IS deathlink, I feel like that was essential. It works a lil weird but should work.
There is one trap for now, you should turn it on and try it.

Some other dumb stuff that you might find just to prove I could for future shitposting.

# Roadmap for v0.2

- Make key items checks, things like keycards, blueprints, freestanding weapons (like sniper in Dam, or Golden Gun in Egypt). Then those items will be added to the pool.
- Make it so you're not allowed to pick up guard weapons because they have that Metal Gear Solid esque finger ID or whatever. This will make it harder to progress in the beginning and you'll have to rely on incoming checks. Each level will logically be able to be beaten though, you'll just have to get good.
- Find cleaner ways to implement mission loadout and kill bond command for deathlink.
- Figure out why sometimes the game crashes and you literally have to close and reopen bizhawk. It's definitely because I'm doing war crimes to the RAM Addresses and I'll have to make safety checks for that.
- More traps. Line mode trap is not working as intended and I'd LOVE to find a way to in-game give all enemies rockets like the cheat.
- Cheats are checks and CAN be used to complete levels. I feel like that's only fair and right now I'm trying to balance items with the large amount of locations currently.

# Special Thanks

Vincent'sSin for compiling every item in the game and logic for them and then for letting me use it for this AP. It's going to be invaluable for moving forward with the checks in the future.

kholdfuzion for his intense and extensive research for the Goldeneye Decomp project and for sharing. This would not be possible without his findings and documentation of hex addresses.

Elfor over at Romhacking.net for sharing the Unlock Everything Patch that's currently used for this AP.

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
