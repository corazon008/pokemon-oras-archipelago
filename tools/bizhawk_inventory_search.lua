-- Scan only the application heap range defined by Encore's memory.h.
-- No guessed inventory address, no writes, no memory dump.
local capture = assert(os.getenv("ORAS_UI_CAPTURE"))
assert(os.getenv("ORAS_UI_CONTINUE") == "1")
dofile(assert(os.getenv("ORAS_UI_SCRIPT")))

local source = assert(io.open(assert(os.getenv("ORAS_INVENTORY_REFERENCE")), "rb"))
local pattern = source:read("*a")
source:close()
assert(#pattern == 0xB90)
local search = dofile(assert(os.getenv("ORAS_INVENTORY_SEARCH_SCRIPT")))
local journal = assert(io.open(capture .. "/inventory-scan-reads.txt", "w"))
local function read(address, length)
    journal:write(string.format("0x%08X %d\n", address, length))
    journal:flush()
    return memory.read_bytes_as_binary_string(address, length, "System Bus")
end
-- CasualPokePlayer/encore 49a3322, src/core/memory.h: HEAP_VADDR / HEAP_SIZE.
local matches, reads = search(read, 0x08000000, 0x10000000, pattern, 0x100000)
journal:close()
local output = assert(io.open(capture .. "/inventory-matches.txt", "w"))
for _, address in ipairs(matches) do output:write(string.format("0x%08X\n", address)) end
output:close()
print(string.format("ORAS_INVENTORY_SCAN reads=%d matches=%d", reads, #matches))
client.exit()
