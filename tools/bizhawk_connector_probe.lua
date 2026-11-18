-- Wrap the unmodified upstream connector with a local-file shutdown signal.
-- Optional native UI and explicitly enabled fail-closed GUARD shim.
-- Downloaded upstream files are not edited; strict mode replaces the GUARD handler.

local directory = assert(os.getenv("ORAS_CONNECTOR_DIRECTORY"))
local stop_path = assert(os.getenv("ORAS_CONNECTOR_STOP"))
local timeout = assert(tonumber(os.getenv("ORAS_CONNECTOR_TIMEOUT")))
package.path = directory .. "/?.lua;" .. package.path

local start_time = os.time()
event.onframeend(function()
    local stop_file = io.open(stop_path, "r")
    local requested = stop_file ~= nil
    if stop_file then stop_file:close() end
    if requested or os.difftime(os.time(), start_time) >= timeout then
        print("ORAS_CONNECTOR probe shutdown")
        client.exit()
    end
end, "ORAS connector probe shutdown")

local boot = os.getenv("ORAS_CONNECTOR_BOOT")
if boot then dofile(boot) end
local objects = os.getenv("ORAS_CONNECTOR_OBJECT_SCRIPT")
if objects then dofile(objects) end
local strict_script = os.getenv("ORAS_CONNECTOR_STRICT_GUARD_SCRIPT")
if strict_script then
    local installed = false
    event.onframeend(function()
        if installed or type(request_handlers) ~= "table" then return end
        assert(request_handlers.GUARD, "Upstream GUARD handler missing")
        local factory = dofile(strict_script)
        request_handlers.GUARD = factory(function(address, length, domain)
            return memory.read_bytes_as_array(address, length, domain)
        end, require("base64").decode, function(address, length, domain)
            local exists = false
            for _, name in pairs(memory.getmemorydomainlist()) do
                if name == domain then exists = true; break end
            end
            if not exists then return false end
            local size = memory.getmemorydomainsize(domain)
            -- Verified Encore behavior: System Bus 4-GiB size truncates to uint32 zero.
            if domain == "System Bus" and size == 0 and emu.getsystemid() == "3DS" then
                size = 0x100000000
            end
            return address + length <= size
        end)
        local marker = assert(io.open(assert(os.getenv("ORAS_CONNECTOR_STRICT_GUARD_READY")), "w"))
        marker:write("installed\n"); marker:close()
        installed = true
    end, "ORAS strict GUARD installation")
end
local post = os.getenv("ORAS_CONNECTOR_POST_SCRIPT")
if post then dofile(post) end
dofile(directory .. "/connector_bizhawk_generic.lua")
