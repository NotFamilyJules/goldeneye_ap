---------------------------------------------------------------------------------------------------------------------------------------
------------------------------------------- BIZHAWK TO ARCHIPELAGO CONNECTION BLOCK ---------------------------------------------------
---------------------------------------------------------------------------------------------------------------------------------------

lua_major, lua_minor = _VERSION:match("Lua (%d+)%.(%d+)")
lua_major = tonumber(lua_major)
lua_minor = tonumber(lua_minor)
ARCHIPELAGO_LUA_DIR = "C:\\ProgramData\\Archipelago\\data\\lua"
if lua_major > 5 or (lua_major == 5 and lua_minor >= 3) then
    dofile(ARCHIPELAGO_LUA_DIR .. "\\lua_5_3_compat.lua")
end
base64 = dofile(ARCHIPELAGO_LUA_DIR .. "\\base64.lua")
if lua_major > 5 or (lua_major == 5 and lua_minor >= 4) then
    socket_lib_path = ARCHIPELAGO_LUA_DIR .. "\\x64\\socket-windows-5-4.dll"
else
    socket_lib_path = ARCHIPELAGO_LUA_DIR .. "\\x64\\socket-windows-5-1.dll"
end
socket_core = assert(package.loadlib(socket_lib_path, "luaopen_socket_core"))()
socket = { socket = socket_core }
json = dofile(ARCHIPELAGO_LUA_DIR .. "\\json.lua")
server = nil
client_socket = nil
function send_receive ()
    message, err = client_socket:receive()
    if err == "closed" then
        print("AP Connection Closed")
        client_socket = nil
        return
    end
    if err == "timeout" then
        return
    end
    if err ~= nil then
        print(err)
        client_socket = nil
        return
    end
    if message == "VERSION" then
        client_socket:send("1\n")
        return
    end
    data = json.decode(message)
    response_list = {}
    i = 1
    while i <= #data do
        if data[i]["type"] == "PING" then
            response_list[i] = {type = "PONG"}
        elseif data[i]["type"] == "SYSTEM" then
            response_list[i] = {type = "SYSTEM_RESPONSE", value = emu.getsystemid()}
        elseif data[i]["type"] == "HASH" then
            response_list[i] = {type = "HASH_RESPONSE", value = gameinfo.getromhash()}
        elseif data[i]["type"] == "READ" then
            response_list[i] = {
                type = "READ_RESPONSE",
                value = base64.encode(memory.read_bytes_as_array(data[i]["address"], data[i]["size"], data[i]["domain"]))
            }
        elseif data[i]["type"] == "GUARD" then
            expected_data = base64.decode(data[i]["expected_data"])
            actual_data = memory.read_bytes_as_array(data[i]["address"], #expected_data, data[i]["domain"])
            matches = true
            for byte_index, byte in ipairs(actual_data) do
                if byte ~= expected_data[byte_index] then
                    matches = false
                    break
                end
            end
            response_list[i] = {type = "GUARD_RESPONSE", value = matches, address = data[i]["address"]}
            -- A failed guard cancels the remaining commands in this request.
            if not matches then
                for pending = i + 1, #data do response_list[pending] = response_list[i] end
                break
            end
        elseif data[i]["type"] == "WRITE" then
            memory.write_bytes_as_array(data[i]["address"], base64.decode(data[i]["value"]), data[i]["domain"])
            response_list[i] = {type = "WRITE_RESPONSE"}
        else
            response_list[i] = {type = "ERROR", err = "Unknown command: " .. data[i]["type"]}
        end
        i = i + 1
    end
    client_socket:send(json.encode(response_list) .. "\n")
end
function main ()
    while true do
        if server == nil and client_socket == nil then
            server, err = socket.socket.tcp4()
            server:setoption("reuseaddr", true)
            res, err = server:bind("localhost", 43055)
            if err == nil then
                res, err = server:listen(0)
                if err == nil then
                    server:settimeout(0)
                    print("Connecting to AP Bizhawk Client.\nPlease wait...")
                else
                    print(err)
                    server:close()
                    server = nil
                end
            else
                print(err)
                server:close()
                server = nil
            end
        end
        if client_socket == nil and server ~= nil then
            client_socket = server:accept()
            if client_socket ~= nil then
                server:close()
                server = nil
                client_socket:settimeout(0)
                print("Bizhawk Client Connected")
            end
        elseif client_socket ~= nil then
            send_receive()
        end

        coroutine.yield()
    end
end
event.onexit(function ()
    if server ~= nil then
        server:close()
    end
end)
co = coroutine.create(main)
function tick ()
    status, err = coroutine.resume(co)
    if not status and err ~= "cannot resume dead coroutine" then
        print("\nERROR: "..err)
        if server ~= nil then
            server:close()
        end
        co = coroutine.create(main)
    end
end
event.onframeend(tick)

---------------------------------------------------------------------------------------------------------------------------------------
---------------------------------------- END OF BIZHAWK TO ARCHIPELAGO CONNECTION BLOCK -----------------------------------------------
---------------------------------------------------------------------------------------------------------------------------------------


---------------------------------------------------------------------------------------------------------------------------------------
-------------------------------------------------------- GOLDENEYE BLOCK---------------------------------------------------------------
---------------------------------------------------------------------------------------------------------------------------------------

do
local BONDDATA_PTR_ADDR = 0x07A0B0  -- BONDATA Pointer Address
local SCREEN_ID_ADDR = 0x02A8C0     
local MISSION_ID_ADDR = 0x02A8F8
local SCREEN_GAMEPLAY = 0x0B

local DELAY_FRAMES = 0              -- Frame delay for testing
local TARGET_EC_VALUE = 1           -- This is the trigger value of the timer_ec to send a pulse
local TARGET_PULSE_COUNT = 4        -- How many pulses to wait until applying loadout

local trigger_armed = false         
local trigger_countdown = -1
local applied = false
local startup_frame = 0
local ec_pulse_count = 0
local last_timer_ec = nil
local last_screen_id = -1
local last_mission_id = -1
local last_bond_base = 0
local STARTUP_READY_MAILBOX_ADDR = 0x7F020

-- Key Item Receive
local KEY_ITEM_FLAGS_MAILBOX_ADDR = 0x7F200
local KEY_ITEM_STATE_MAILBOX_ADDR = 0x7F204

-- Freestanding Objects
local FREESTANDING_RESULT_MAILBOX_ADDR = 0x7F1C0
local FREESTANDING_TARGET_COUNT_ADDR = 0x7F1C4
local FREESTANDING_TARGET_LIST_ADDR = 0x7F150
local FREESTANDING_TARGET_BITS = 28
local TANK_OWNED_ADDR = 0x7F20A
local TANK_DESCRIPTOR_ADDR = 0x7F210
local tank_source = nil
local ITEM_TOKEN = 88
local INV_ITEM_NONE = -1
local INV_ITEM_WEAPON = 1
local INV_ITEM_PROP = 2
local INV_ITEM_SIZE = 0x14

local OFF_HANDS_BASE = 0x870
local HAND_OFF_TIMER_EC = 0x1C
local HAND_OFF_WEAPONNUM = 0x00
local HAND_OFF_WEAPONNUM_WATCH = 0x04
local HAND_OFF_CURRENT_ANIM = 0x2C
local HAND_OFF_AMMO_IN_MAG = 0x30
local HAND_OFF_NEXT_WEAPON = 0x40
local HAND_OFF_ANIM_TRIGGER = 0x48
local OFF_HAND_INVISIBLE = 0x7F8
local OFF_HAND_ITEM = 0x800
local OFF_EQUIP_CUR = 0x11F0
local OFF_FIELD_2A44 = 0x2A44
local OFF_LOCK_HAND_MODEL = 0x2A4C
local startup_ready_sent = false
local prev_screen_id = -1

local ONSCREEN_PROP_LIST = 0x071620
local ONSCREEN_PROP_COUNT = 0x071DF4
local PROP_POOL = 0x069C38
local PROP_SIZE = 0x34
local PROP_MAX = 600
local PROP_OFF_OBJ = 0x04
local OBJ_OFF_TYPE = 0x03
local OBJ_OFF_FLAGS = 0x08
local OBJ_OFF_PROP = 0x10
local WEP_OFF_WEAPONNUM = 0x80
local PROPFLAG_00080000 = 0x00080000
local PROPFLAG_UNCOLLECTABLE = 0x00100000
local PROPFLAG_CANNOT_ACTIVATE = 0x02000000
local OFF_INV_HEAD = 0x11E0
local OFF_INV_POOL = 0x11E4
local OFF_INV_MAX = 0x11E8
local freestanding_targets = {}
local freestanding_signature = ""

local function read_u32(addr)
    return mainmemory.read_u32_be(addr)
end

local function write_u32(addr, value)
    mainmemory.write_u32_be(addr, value)
end

local function write_s32(addr, value)
    mainmemory.write_s32_be(addr, value)
end

local function to_rdram_ptr(value)
    if value == 0 then
        return 0
    end
    if value > 0 and value < 0x800000 then
        return value
    end
    if value >= 0x80000000 and value < 0x80800000 then
        return value - 0x80000000
    end
    return 0
end

local function reset_state()
    startup_frame = 0
    ec_pulse_count = 0
    last_timer_ec = nil
    startup_ready_sent = false
end

local function get_bonddata_base()
    return to_rdram_ptr(read_u32(BONDDATA_PTR_ADDR))    -- Function to get the current BONDDATA base address
end

local function has_result_bit(value, index)
    return math.floor(value / (2 ^ index)) % 2 == 1
end

local function set_result_bit(index)
    local result = read_u32(FREESTANDING_RESULT_MAILBOX_ADDR)
    if not has_result_bit(result, index) then
        write_u32(FREESTANDING_RESULT_MAILBOX_ADDR, result + (2 ^ index))
    end
end

local function unlink_inventory_entry(bond_base, entry_ptr)
    local next_ptr = to_rdram_ptr(read_u32(entry_ptr + 0x0C))
    local prev_ptr = to_rdram_ptr(read_u32(entry_ptr + 0x10))
    local head_ptr = to_rdram_ptr(read_u32(bond_base + OFF_INV_HEAD))
    if next_ptr == 0 or prev_ptr == 0 then return false end
    if next_ptr == entry_ptr and prev_ptr == entry_ptr then
        write_u32(bond_base + OFF_INV_HEAD, 0)
    else
        write_u32(prev_ptr + 0x0C, 0x80000000 + next_ptr)
        write_u32(next_ptr + 0x10, 0x80000000 + prev_ptr)
        if head_ptr == entry_ptr then write_u32(bond_base + OFF_INV_HEAD, 0x80000000 + next_ptr) end
    end
    write_s32(entry_ptr, INV_ITEM_NONE)
    for offset = 4, INV_ITEM_SIZE - 4, 4 do write_u32(entry_ptr + offset, 0) end
    return true
end

local function inventory_entries(bond_base)
    local entries = {}
    local head = to_rdram_ptr(read_u32(bond_base + OFF_INV_HEAD))
    local pool = to_rdram_ptr(read_u32(bond_base + OFF_INV_POOL))
    local max_items = read_u32(bond_base + OFF_INV_MAX)
    if head == 0 or pool == 0 or max_items <= 0 or max_items > 128 then return entries end
    local current = head
    local seen = {}
    while current > 0 and not seen[current] do
        seen[current] = true
        entries[#entries + 1] = {ptr=current, type=mainmemory.read_s32_be(current), value=read_u32(current + 4)}
        current = to_rdram_ptr(read_u32(current + 0x0C))
    end
    return entries
end

local function prop_is_onscreen(prop_ptr)
    local count = read_u32(ONSCREEN_PROP_COUNT)
    if count > 512 then return false end
    for index = 0, count - 1 do
        if to_rdram_ptr(read_u32(ONSCREEN_PROP_LIST + index * 4)) == prop_ptr then
            return true
        end
    end
    return false
end

local function enable_proxy_collection(obj_ptr)
    local flags = read_u32(obj_ptr + OBJ_OFF_FLAGS)
    flags = flags & (~PROPFLAG_00080000)
    flags = flags & (~PROPFLAG_UNCOLLECTABLE)
    flags = flags & (~PROPFLAG_CANNOT_ACTIVATE)
    write_u32(obj_ptr + OBJ_OFF_FLAGS, flags)
end

local function clear_token_hand(bond_base)
    local hand = bond_base + OFF_HANDS_BASE
    write_u32(hand + HAND_OFF_WEAPONNUM, 0)
    write_s32(hand + HAND_OFF_WEAPONNUM_WATCH, -1)
    write_u32(hand + HAND_OFF_CURRENT_ANIM, 0)
    write_u32(hand + HAND_OFF_AMMO_IN_MAG, 0)
    write_u32(hand + HAND_OFF_NEXT_WEAPON, 0)
    write_u32(hand + HAND_OFF_ANIM_TRIGGER, 0)
    write_s32(bond_base + OFF_HAND_INVISIBLE, 0)
    write_u32(bond_base + OFF_HAND_ITEM, 0)
    write_s32(bond_base + OFF_FIELD_2A44, INV_ITEM_NONE)
    write_u32(bond_base + OFF_LOCK_HAND_MODEL, 0)
    write_u32(bond_base + OFF_EQUIP_CUR, 0)
end

local function rebuild_freestanding_targets()
    local count = read_u32(FREESTANDING_TARGET_COUNT_ADDR)
    if count > 32 then count = 0 end
    -- 1. Read each packed byte once; unchanged descriptors need no decoding.
    local packed_bytes = {}
    for index = 0, math.ceil(count * FREESTANDING_TARGET_BITS / 8) - 1 do
        packed_bytes[index + 1] = mainmemory.readbyte(FREESTANDING_TARGET_LIST_ADDR + index)
    end
    local signature = tostring(count) .. ":" .. table.concat(packed_bytes, ",")
    if signature == freestanding_signature then return end
    freestanding_signature = signature
    -- 2. Decode only a newly published target list.
    local descriptors = {}
    for index = 0, count - 1 do
        local descriptor = 0
        for bit = 0, FREESTANDING_TARGET_BITS - 1 do
            local packed_bit = index * FREESTANDING_TARGET_BITS + bit
            local byte = packed_bytes[math.floor(packed_bit / 8) + 1]
            descriptor = descriptor + math.floor(byte / (2 ^ (packed_bit % 8))) % 2 * (2 ^ bit)
        end
        descriptors[index + 1] = descriptor
    end
    freestanding_targets = {}
    for index = 0, count - 1 do
        local descriptor = descriptors[index + 1]
        local target = {
            index=index,
            kind=math.floor(descriptor / 0x4000000) % 4 + 1,
            npc_weapon=math.floor(descriptor / 0x2000000) % 2 == 1,
            model=math.floor(descriptor / 0x10000) % 0x200,
            pad=descriptor % 0x10000,
            objects={},
            bound=false,
        }
        freestanding_targets[#freestanding_targets + 1] = target
    end
end

local function bind_preplaced_freestanding_objects()
    local all_bound = true
    for _, target in ipairs(freestanding_targets) do
        if not target.bound then all_bound = false end
    end
    if all_bound then return end

    -- 1. Inspect each native prop once for all unresolved source identities.
    for prop_index = 0, PROP_MAX - 1 do
        local prop_ptr = PROP_POOL + prop_index * PROP_SIZE
        local obj_ptr = to_rdram_ptr(read_u32(prop_ptr + PROP_OFF_OBJ))
        local prop_type = mainmemory.readbyte(prop_ptr)
        if obj_ptr > 0 and (prop_type == 1 or prop_type == 4)
            and to_rdram_ptr(read_u32(obj_ptr + OBJ_OFF_PROP)) == prop_ptr then
            local model_pad = read_u32(obj_ptr + 4)
            local model = math.floor(model_pad / 0x10000) % 0x10000
            local pad = model_pad % 0x10000
            local weapon_number = mainmemory.readbyte(obj_ptr + WEP_OFF_WEAPONNUM)
            local guard_gun = mainmemory.readbyte(obj_ptr + OBJ_OFF_TYPE) == 8
                and (weapon_number < 33 or weapon_number == ITEM_TOKEN)
                and (read_u32(obj_ptr + OBJ_OFF_FLAGS) & 0x4000) ~= 0
            for _, target in ipairs(freestanding_targets) do
                if not target.bound and model == target.model and pad == target.pad
                    and guard_gun == target.npc_weapon then
                    target.objects[#target.objects + 1] = {obj=obj_ptr, prop=prop_ptr, was_live=false, collected=false}
                end
            end
        end
    end
    -- 2. Finish binding after the scan so grouped sources keep every match.
    for _, target in ipairs(freestanding_targets) do
        if #target.objects > 0 then target.bound = true end
    end
end

 -- This function is called every frame to check for freestanding object pickups and update the result mailbox accordingly.

-- target.kind values:
-- 1 - Single weapon pickup; uses a token.	[Dam Sniper Rifle (code.gen line 512)]
-- 2 - Key or mission item; tracks the actual object being collected.	[Runway Ignition Key (code.gen line 513)]
-- 3 - Grouped weapon pickups sharing one location; uses tokens.	[Bunker 2’s six Throwing Knives (code.gen line 523)]
-- 4 - Supplies: native type 21 armor uses the native acquisition hook;
--     type 7 magazines also use native acquisition; type 20 boxes use tokens.

local function update_tank_visibility()
    -- 1. Bind only the generated mission tank, using its native type and source.
    local descriptor = read_u32(TANK_DESCRIPTOR_ADDR)
    if descriptor == 0 then return end
    if tank_source == nil then
        for index = 0, PROP_MAX - 1 do
            local prop = PROP_POOL + index * PROP_SIZE
            local obj = to_rdram_ptr(read_u32(prop + PROP_OFF_OBJ))
            if obj > 0 and mainmemory.readbyte(obj + OBJ_OFF_TYPE) == 45
                and read_u32(obj + 4) == descriptor
                and to_rdram_ptr(read_u32(obj + OBJ_OFF_PROP)) == prop then
                tank_source = {obj=obj, prop=prop, enabled=mainmemory.readbyte(prop + 1) & 4}
                break
            end
        end
    end
    if tank_source == nil then return end
    -- 2. Validate the native pair before touching the live prop's enable bit.
    local obj, prop = tank_source.obj, tank_source.prop
    if to_rdram_ptr(read_u32(obj + OBJ_OFF_PROP)) ~= prop
        or to_rdram_ptr(read_u32(prop + PROP_OFF_OBJ)) ~= obj then
        tank_source = nil
        return
    end
    -- chrpropDisable/Enable use prop.flags bit 4; the native render list requires it.
    -- Entry is independently gated at g_BondCanEnterTank in the ROM patch.
    local flags = mainmemory.readbyte(prop + 1)
    local enabled = mainmemory.readbyte(TANK_OWNED_ADDR) == 1 and tank_source.enabled or 0
    local desired = (flags & (~4)) | enabled
    if flags ~= desired then mainmemory.writebyte(prop + 1, desired) end
end

 local function update_freestanding_pickups(bond_base)
    rebuild_freestanding_targets()
    bind_preplaced_freestanding_objects()
    local entries = inventory_entries(bond_base)
    local token_entry = nil
    for _, entry in ipairs(entries) do
        if entry.type == INV_ITEM_WEAPON and entry.value == ITEM_TOKEN then token_entry = entry.ptr end
    end
    local token_in_hand = read_u32(bond_base + OFF_HANDS_BASE + HAND_OFF_WEAPONNUM) == ITEM_TOKEN
        or read_u32(bond_base + OFF_EQUIP_CUR) == ITEM_TOKEN

    for _, target in ipairs(freestanding_targets) do
        for _, tracked in ipairs(target.objects) do
            local live_prop = to_rdram_ptr(read_u32(tracked.obj + OBJ_OFF_PROP))
            if tracked.obj > 0 then
                if live_prop > 0 then

                    -- Native armor and ammunition hooks retain their object layouts.
                    -- Only weapon sources use the temporary inventory token.

                    if (target.kind == 1 or target.kind == 3) and prop_is_onscreen(live_prop)
                        and (not target.npc_weapon or read_u32(live_prop + 0x1C) == 0) then
                        -- A configured NPC keeps its weapon until it drops it normally.
                        mainmemory.writebyte(tracked.obj + WEP_OFF_WEAPONNUM, ITEM_TOKEN)
                        enable_proxy_collection(tracked.obj)
                        tracked.was_live = true
                    end
                end
                if target.kind == 2 and tracked.prop > 0 and not tracked.collected then
                    local player_prop = to_rdram_ptr(read_u32(bond_base + 0xA8))
                    local parent_prop = to_rdram_ptr(read_u32(tracked.prop + 0x1C))
                    for _, entry in ipairs(entries) do
                        if entry.type == INV_ITEM_PROP and to_rdram_ptr(entry.value) == tracked.prop then
                            set_result_bit(target.index)
                            unlink_inventory_entry(bond_base, entry.ptr)
                            tracked.collected = true
                        end
                    end
                    -- Native key and mission-item pickups parent the exact setup prop
                    -- to Bond even when no inventory node survives to the Lua callback.
                    -- propExecuteTickOperation reparents this exact source only
                    -- after successful native pickup or scripted BondCollectObject.
                    -- A handoff need not happen within walking pickup distance.
                    if not tracked.collected and player_prop > 0 and parent_prop == player_prop then
                        set_result_bit(target.index)
                        tracked.collected = true
                    end
                elseif tracked.was_live and live_prop == 0
                    and (token_entry or token_in_hand) then
                    set_result_bit(target.index)
                    tracked.was_live = false
                end
            end
        end
    end
    if token_entry then unlink_inventory_entry(bond_base, token_entry) end
    if token_in_hand then clear_token_hand(bond_base) end
end

event.onframestart(function()
    local screen_id = read_u32(SCREEN_ID_ADDR)              -- Set variables upon start
    local mission_id = read_u32(MISSION_ID_ADDR)
    local bond_base = get_bonddata_base()

    -- if the screen, mission, or bondbase_id ever changes, reset 
    if screen_id ~= last_screen_id or mission_id ~= last_mission_id or bond_base ~= last_bond_base then
        reset_state()
        freestanding_targets = {}
        freestanding_signature = ""
        tank_source = nil
        if screen_id == SCREEN_GAMEPLAY and mission_id ~= 0 and bond_base > 0 then
            write_u32(STARTUP_READY_MAILBOX_ADDR, 0)
            write_u32(FREESTANDING_RESULT_MAILBOX_ADDR, 0)
            write_u32(KEY_ITEM_FLAGS_MAILBOX_ADDR, 0)
            write_u32(KEY_ITEM_STATE_MAILBOX_ADDR, 0)
            mainmemory.writebyte(0x7F209, 0) -- Native item acquisition stays disabled until slot options arrive.
            write_u32(0x7F20C, 0) -- Guard ammunition acquisitions belong only to this attempt.
            mainmemory.writebyte(TANK_OWNED_ADDR, 0)
            write_u32(TANK_DESCRIPTOR_ADDR, 0)
        end
    end

    last_screen_id = screen_id
    last_mission_id = mission_id
    last_bond_base = bond_base

    if prev_screen_id == 0x0C and screen_id ~= 0x0C and screen_id ~= 0x07 then  -- if you try to go the next level
        mainmemory.write_u32_be(0x2A8C0, 0x07)                                  -- get fucked
    end
    prev_screen_id = screen_id

    if screen_id ~= SCREEN_GAMEPLAY or mission_id == 0 or bond_base <= 0 then
        return
    end

    -- this is the frame counter from startup
    startup_frame = startup_frame + 1

    local hand_base = bond_base + OFF_HANDS_BASE    
    local timer_ec = read_u32(hand_base + HAND_OFF_TIMER_EC)

    if last_timer_ec ~= TARGET_EC_VALUE and timer_ec == TARGET_EC_VALUE then
        ec_pulse_count = ec_pulse_count + 1
    end

    if ec_pulse_count >= TARGET_PULSE_COUNT and not startup_ready_sent then
        write_u32(STARTUP_READY_MAILBOX_ADDR, 1)
        startup_ready_sent = true
    end

    -- Pickup inventory evidence is transient, so consume it before the game frame.
    update_tank_visibility()
    update_freestanding_pickups(bond_base)
    last_timer_ec = timer_ec
end)

event.onframeend(function()
    local screen_id = read_u32(SCREEN_ID_ADDR)
    local mission_id = read_u32(MISSION_ID_ADDR)
    local bond_base = get_bonddata_base()
    if screen_id == SCREEN_GAMEPLAY and mission_id ~= 0 and bond_base > 0 then
        local key_flags = read_u32(KEY_ITEM_FLAGS_MAILBOX_ADDR)
        local key_state = read_u32(KEY_ITEM_STATE_MAILBOX_ADDR)
        local key_mission_id = math.floor(key_state / 0x100) % 0x100
        if (key_flags ~= 0 or key_state ~= 0) and key_mission_id ~= mission_id then
            write_u32(KEY_ITEM_FLAGS_MAILBOX_ADDR, 0)
            write_u32(KEY_ITEM_STATE_MAILBOX_ADDR, 0)
        end
        -- ITEM_TOKEN is equipped during the game frame, before this callback.
        update_freestanding_pickups(bond_base)
    end
end)
end

while true do

    emu.frameadvance()

end
