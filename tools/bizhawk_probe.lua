-- Capability inventory only: no game memory reads, writes, input, or save operations.
-- Output stays local. Run with an isolated emulator profile.

local function json(value)
    local kind = type(value)
    if kind == "string" then
        return '"' .. value:gsub('[%z\1-\31\\"]', function(char)
            return string.format("\\u%04x", string.byte(char))
        end) .. '"'
    elseif kind == "boolean" or kind == "number" then
        return tostring(value)
    elseif kind == "table" then
        local keys = {}
        for key in pairs(value) do
            assert(type(key) == "string", "Report objects require string keys")
            keys[#keys + 1] = key
        end
        table.sort(keys)
        local fields = {}
        for _, key in ipairs(keys) do
            fields[#fields + 1] = json(key) .. ":" .. json(value[key])
        end
        return "{" .. table.concat(fields, ",") .. "}"
    end
    error("Unsupported report value: " .. kind)
end

local function observe(fn)
    if type(fn) ~= "function" then
        return {ok = false, error = "API unavailable"}
    end
    local ok, result = pcall(fn)
    if ok then
        return {ok = true, value = result}
    end
    return {ok = false, error = tostring(result)}
end

local frame_limit = tonumber(os.getenv("ORAS_PROBE_FRAMES") or "0")
assert(frame_limit and frame_limit >= 0 and frame_limit <= 3600
    and frame_limit % 1 == 0, "ORAS_PROBE_FRAMES must be an integer from 0 to 3600")

local report = {
    schema_version = 1,
    kind = "capability_inventory",
    lua_version = _VERSION,
    memory_reads = 0,
    memory_writes = 0,
    requested_frames = frame_limit,
    completed_frames = 0,
    bizhawk_version = observe(function() return client.getversion() end),
    system = observe(function() return emu.getsystemid() end),
    frame_start = observe(function() return emu.framecount() end),
    domains = {},
    api = {
        -- NLua can expose callable CLR delegates as userdata, not Lua functions.
        domain_list_present = memory.getmemorydomainlist ~= nil,
        domain_size_present = memory.getmemorydomainsize ~= nil,
        read_bytes_present = memory.read_bytes_as_array ~= nil,
        write_bytes_present = memory.write_bytes_as_array ~= nil,
    },
}

local ok, domains = pcall(memory.getmemorydomainlist)
report.domain_inventory_ok = ok and type(domains) == "table"
if report.domain_inventory_ok then
    -- BizHawk returns a zero-indexed table, so ipairs would miss its first entry.
    for _, name in pairs(domains) do
        if type(name) == "string" then
            report.domains[name] = observe(function()
                return memory.getmemorydomainsize(name)
            end)
        end
    end
else
    report.domain_inventory_error = tostring(domains)
end

local socket_ok, socket_result = pcall(require, "socket")
report.lua_socket_loadable = socket_ok
if not socket_ok then
    report.lua_socket_error = tostring(socket_result)
end

local function emit()
    local encoded = json(report)
    local path = os.getenv("ORAS_PROBE_OUTPUT")
    if path and path ~= "" then
        local file = assert(io.open(path, "w"))
        file:write(encoded, "\n")
        file:close()
    end
    print("ORAS_PROBE " .. encoded)
end

report.status = "inventory_complete"
emit()

for frame = 1, frame_limit do
    emu.frameadvance()
    report.completed_frames = frame
end

report.frame_end = observe(function() return emu.framecount() end)
report.status = "complete"
emit()

local screenshot = os.getenv("ORAS_PROBE_SCREENSHOT")
if screenshot and screenshot ~= "" and client.screenshot ~= nil then
    client.screenshot(screenshot)
end

if os.getenv("ORAS_PROBE_EXIT") == "1" then
    client.exit()
end
