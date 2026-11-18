-- Run the pinned, unedited upstream dispatcher with fake emulator/socket APIs.
-- WRITE only increments a test counter. No real emulator or ROM is loaded.
local strict = os.getenv("ORAS_FIXTURE_STRICT") == "1"
local frames, sent, writes, received = 0, 0, 0, 0
local callbacks = {}
local active
local cases = {"valid", "invalid-domain", "short", "decode-error"}
package.preload.lua_5_3_compat = function() return {} end
package.preload.base64 = function() return {
    decode=function(data)
        if data == "invalid" then error("malformed fixture") end
        return {1,2,3,4}
    end,
    encode=function() return "fixture-read" end,
} end
package.preload.json = function() return {
    decode=function(message)
        active = message
        local guard = {type="GUARD", address=16, domain="System Bus", expected_data="fixture"}
        if message == "valid" then
            return {guard, {type="READ", address=16, size=4, domain="System Bus"}}
        end
        if message == "invalid-domain" then guard.domain = "missing" end
        if message == "short" then guard.domain = "short" end
        if message == "decode-error" then guard.expected_data = "invalid" end
        return {guard, {type="WRITE", address=16, value="fixture", domain="System Bus"}}
    end,
    encode=function(responses)
        assert(#responses == 2)
        if active == "valid" then
            assert(responses[1].value == true and responses[2].type == "READ_RESPONSE")
        elseif strict then
            assert(responses[1].type == "GUARD_RESPONSE" and responses[1].value == false)
            assert(responses[2].type == "GUARD_RESPONSE" and responses[2].value == false)
        else
            assert(responses[2].type == "WRITE_RESPONSE")
            if active == "short" then assert(responses[1].value == true)
            else assert(responses[1].type == "ERROR") end
        end
        return "fixture-response"
    end,
} end
local tcp_client = {
    settimeout=function() end,
    receive=function()
        received = received + 1
        if cases[received] then return cases[received], nil end
        return nil, "timeout"
    end,
    send=function() sent=sent+1 end,
}
package.preload.socket = function() return {socket={
    gettime=function() return frames / 60 end,
    tcp4=function() return {
        bind=function() return 1 end, listen=function() return 1 end,
        settimeout=function() end, close=function() end,
        accept=function() return tcp_client, nil end,
    } end,
}} end
memory = {
    getmemorydomainlist=function() return {[0]="System Bus", [1]="missing", [2]="short"} end,
    getmemorydomainsize=function() return 64 end,
    read_bytes_as_array=function(_, _, domain)
        if domain == "missing" then error("invalid memory domain fixture") end
        if domain == "short" then return {1,2} end
        return {1,2,3,4}
    end,
    write_bytes_as_array=function() writes=writes+1 end,
}
event = {onexit=function() end, onframeend=function(fn) callbacks[#callbacks+1]=fn end}
client = {getversion=function() return "2.11.1" end, exit=function() error("Unexpected fixture exit") end}
gameinfo = {getromhash=function() return "synthetic" end}
gui = {addmessage=function() end}
emu = {
    getsystemid=function() return "3DS" end,
    framecount=function() return frames end,
    frameadvance=function()
        frames=frames+1
        for _, callback in ipairs(callbacks) do callback() end
        if sent == #cases then error("FIXTURE_DONE") end
        assert(frames < 200, "Fixture timeout")
    end,
}
local ok, err = pcall(dofile, assert(os.getenv("ORAS_FIXTURE_WRAPPER")))
assert(not ok and tostring(err):find("FIXTURE_DONE", 1, true), tostring(err))
assert(writes == (strict and 0 or 3), "Unexpected mock WRITE count")
print("STRICT_GUARD_FIXTURE_PASS")
