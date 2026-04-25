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
                    print("Connecting to AP Bizhawk Client...")
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

while true do
    emu.frameadvance()
end
