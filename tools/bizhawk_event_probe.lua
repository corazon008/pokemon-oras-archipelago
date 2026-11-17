-- Read-only EventWork6 search/observation after native UI, never write game memory.
local capture = assert(os.getenv("ORAS_UI_CAPTURE"))
local mode = assert(os.getenv("ORAS_EVENT_MODE"))
local length = 0x504 -- PKHeX SaveBlockAccessor6AO, block 19.
local journal = assert(io.open(capture .. "/event-read-requests.txt", "w"))
local address
local function read(at, size)
    journal:write(string.format("0x%08X %d\n", at, size)); journal:flush()
    local bytes = memory.read_bytes_as_binary_string(at, size, "System Bus")
    assert(type(bytes) == "string" and #bytes == size, "Incomplete event memory read")
    return bytes
end
local function sample(name)
    local bytes = read(address, length)
    local file = assert(io.open(capture .. "/" .. name .. ".bin", "wb"))
    file:write(bytes); file:close()
end
assert(os.getenv("ORAS_UI_CONTINUE") == "1")
if mode == "read" then
    address = assert(tonumber(os.getenv("ORAS_EVENT_ADDRESS")))
    local samples = {}
    for index in (os.getenv("ORAS_EVENT_SAMPLE_STEPS") or ""):gmatch("%d+") do
        samples[tonumber(index)] = true
    end
    ORAS_UI_AFTER_STEP = function(index)
        if samples[index] then sample(string.format("event-step-%02d", index)) end
    end
else
    assert(mode == "scan", "Unsupported event observation mode")
end
dofile(assert(os.getenv("ORAS_UI_SCRIPT")))
if mode == "scan" then
    local file = assert(io.open(assert(os.getenv("ORAS_EVENT_REFERENCE")), "rb"))
    local pattern = file:read("*a"); file:close()
    assert(#pattern == length, "Unexpected event reference length")
    local search = dofile(assert(os.getenv("ORAS_EVENT_SEARCH_SCRIPT")))
    -- Encore memory.h HEAP_VADDR/HEAP_SIZE, no inventory-relative address assumption.
    local matches = search(read, 0x08000000, 0x10000000, pattern, 0x100000)
    local output = assert(io.open(capture .. "/event-matches.txt", "w"))
    for _, at in ipairs(matches) do output:write(string.format("0x%08X\n", at)) end
    output:close()
else
    sample("event-final")
end
journal:close()
client.exit()
