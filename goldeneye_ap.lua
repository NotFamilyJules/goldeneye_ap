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
            res, err = server:bind("localhost", 43055)
            if err == nil then
                res, err = server:listen(0)
                if err == nil then
                    server:settimeout(0)
                    print("Connecting to AP Bizhawk Client.\nPlease wait...")
                else
                    print(err)
                end
            else
                print(err)
            end
        end
        if client_socket == nil then
            client_socket = server:accept()
            if client_socket ~= nil then
                server:close()
                server = nil
                client_socket:settimeout(0)
                print("Bizhawk Client Connected")
            end
        else
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

-- Freestanding Objects
local FREESTANDING_RESULT_MAILBOX_ADDR = 0x7F1C0
local FREESTANDING_TARGET_COUNT_ADDR = 0x7F1C4
local FREESTANDING_TARGET_LIST_ADDR = 0x7F1C8
local FREESTANDING_TARGET_ENTRY_SIZE = 4

local OFF_HANDS_BASE = 0x870
local HAND_OFF_TIMER_EC = 0x1C
local startup_ready_sent = false
local prev_screen_id = -1

local ONSCREEN_PROP_LIST = 0x071620
local ONSCREEN_PROP_COUNT = 0x071DF4
local PROP_OFF_OBJ = 0x04
local PROP_OFF_PREV = 0x24
local PROP_OFF_NEXT = 0x28
local OBJ_OFF_TYPE = 0x03
local WEP_OFF_WEAPONNUM = 0x80
local PROPDEF_COLLECTABLE = 0x08
local ITEM_SNIPERRIFLE = 17
local ITEM_TOKEN = 88
local DAM_MISSION_ID = 0x01
local patched_freestanding_prop = 0
local freestanding_proxy_sent = false

local function read_u32(addr)
    return mainmemory.read_u32_be(addr)
end

local function write_u32(addr, value)
    mainmemory.write_u32_be(addr, value)
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
    write_u32(STARTUP_READY_MAILBOX_ADDR, 0)
end

local function get_bonddata_base()
    return to_rdram_ptr(read_u32(BONDDATA_PTR_ADDR))    -- Function to get the current BONDDATA base address
end

local function reset_freestanding_proxy()
    patched_freestanding_prop = 0
    freestanding_proxy_sent = false
    write_u32(FREESTANDING_PROXY_MAILBOX_ADDR, 0)
end

local function find_visible_dam_sniper() -- TESTING FREESTANDING VIABILITY
    local on_screen_count = read_u32(ONSCREEN_PROP_COUNT)

    for i = 0, on_screen_count - 1 do
        local prop_ptr = to_rdram_ptr(read_u32(ONSCREEN_PROP_LIST + i * 4))
        if prop_ptr ~= 0 then
            local obj_ptr = to_rdram_ptr(read_u32(prop_ptr + PROP_OFF_OBJ))
            if obj_ptr ~= 0 then
                local obj_type = mainmemory.readbyte(obj_ptr + OBJ_OFF_TYPE)
                local weapon_id = mainmemory.readbyte(obj_ptr + WEP_OFF_WEAPONNUM)
                if obj_type == PROPDEF_COLLECTABLE and (weapon_id == ITEM_SNIPERRIFLE or weapon_id == ITEM_TOKEN) then
                    return prop_ptr, obj_ptr
                end
            end
        end
    end

    return 0, 0
end

local function update_dam_sniper_proxy(screen_id, mission_id)
    if screen_id ~= SCREEN_GAMEPLAY or mission_id ~= DAM_MISSION_ID then
        return
    end

    if patched_freestanding_prop == 0 then
        local prop_ptr, obj_ptr = find_visible_dam_sniper()
        if prop_ptr == 0 or obj_ptr == 0 then
            return
        end
        patched_freestanding_prop = prop_ptr
    end

    local obj_ptr = to_rdram_ptr(read_u32(patched_freestanding_prop + PROP_OFF_OBJ))
    if obj_ptr ~= 0 then
        mainmemory.writebyte(obj_ptr + WEP_OFF_WEAPONNUM, ITEM_TOKEN)  -- turn the real pickup into the AP proxy pickup
    end

    local prev_ptr = to_rdram_ptr(read_u32(patched_freestanding_prop + PROP_OFF_PREV))
    local next_ptr = to_rdram_ptr(read_u32(patched_freestanding_prop + PROP_OFF_NEXT))

    if not freestanding_proxy_sent and patched_freestanding_prop ~= 0 and prev_ptr == 0 and next_ptr == 0 then
        freestanding_proxy_sent = true
        write_u32(FREESTANDING_PROXY_MAILBOX_ADDR, FREESTANDING_PROXY_MAILBOX_QUEUED)
    end
end

event.onframestart(function()
    local screen_id = read_u32(SCREEN_ID_ADDR)              -- Set variables upon start
    local mission_id = read_u32(MISSION_ID_ADDR)
    local bond_base = get_bonddata_base()

    -- if the screen, mission, or bondbase_id ever changes, reset 
    if screen_id ~= last_screen_id or mission_id ~= last_mission_id or bond_base ~= last_bond_base then
        reset_state()
        reset_freestanding_proxy()
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

    last_timer_ec = timer_ec
end)


event.onframeend(function()
    local screen_id = read_u32(SCREEN_ID_ADDR)
    local mission_id = read_u32(MISSION_ID_ADDR)
    local bond_base = get_bonddata_base()
    if screen_id ~= SCREEN_GAMEPLAY or mission_id == 0 or bond_base <= 0 then
        return
    end

    update_dam_sniper_proxy(screen_id, mission_id)
end)

while true do

    emu.frameadvance()

end
