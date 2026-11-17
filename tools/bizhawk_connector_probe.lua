-- Wrap the unmodified upstream connector with a local-file shutdown signal.
-- Optional native UI boot; memory/network handlers remain upstream and unmodified.

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
local post = os.getenv("ORAS_CONNECTOR_POST_SCRIPT")
if post then dofile(post) end
dofile(directory .. "/connector_bizhawk_generic.lua")
