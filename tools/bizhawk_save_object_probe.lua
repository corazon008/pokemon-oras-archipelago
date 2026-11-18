-- Bounded read-only static references and object-header search. No game writes.
local capture = assert(os.getenv("ORAS_OBJECT_CAPTURE"))
assert(emu.getsystemid() == "3DS", "Object search requires 3DS")
local exists = false
for _, name in pairs(memory.getmemorydomainlist()) do
    if name == "System Bus" then exists = true; break end
end
assert(exists, "Exact System Bus domain is required")
local domain_size = memory.getmemorydomainsize("System Bus")
-- Same verified Encore uint32 truncation handled by the strict GUARD shim.
if domain_size == 0 then domain_size = 0x100000000 end
assert(domain_size == 0x100000000, "Unexpected 3DS System Bus size")
local file = assert(io.open(assert(os.getenv("ORAS_OBJECT_PLAN")), "rb"))
local plan = file:read("*a"); file:close()
local cursor = 1
local function integer()
    local value
    value, cursor = string.unpack("<I4", plan, cursor)
    return value
end
local journal = assert(io.open(capture .. "/read-requests.txt", "w"))
local function read(address, length)
    assert(address >= 0 and length > 0 and address + length <= domain_size)
    journal:write(string.format("0x%08X %d\n", address, length)); journal:flush()
    local bytes = memory.read_bytes_as_binary_string(address, length, "System Bus")
    assert(type(bytes) == "string" and #bytes == length, "Incomplete object read")
    return bytes
end
local count = integer()
assert(count >= 1 and count <= 32)
for _ = 1, count do
    local address, length = integer(), integer()
    assert(length >= 1 and length <= 256)
    local expected = plan:sub(cursor, cursor + length - 1)
    assert(#expected == length)
    cursor = cursor + length
    assert(read(address, length) == expected, "Static code/table or known object header mismatch")
end
local length = integer()
assert(length == 2004, "Unexpected block47 object pattern size")
local pattern = plan:sub(cursor)
assert(#pattern == length)
local search = dofile(assert(os.getenv("ORAS_OBJECT_SEARCH")))
local matches = search(read, 0x08000000, 0x10000000, pattern, 0x100000)
for _, address in ipairs(matches) do
    assert(address % 4 == 0, "Unaligned object match")
    assert(read(address, length) == pattern, "Object changed after heap search")
end
local manager_table = os.getenv("ORAS_OBJECT_MANAGER_TABLE")
if manager_table then
    local table_address = assert(tonumber(manager_table))
    assert(table_address % 4 == 0 and table_address >= 0x080722D0
           and table_address + 232 <= 0x10000000, "Invalid manager table range")
    local function capture_bytes(name, bytes)
        local output = assert(io.open(capture .. "/" .. name, "wb"))
        output:write(bytes); output:close()
    end
    local root = read(table_address - 0x722D0, 8)
    capture_bytes("manager-root.bin", root)
    local pointers = read(table_address, 232)
    capture_bytes("manager-table.bin", pointers)
    local headers = {}
    for index = 0, 57 do
        local address = string.unpack("<I4", pointers, index * 4 + 1)
        assert(address % 4 == 0 and address >= 0x08000000
               and address + 4 <= 0x10000000, "Invalid manager object pointer")
        headers[#headers + 1] = read(address, 4)
    end
    capture_bytes("manager-headers.bin", table.concat(headers))
    local metadata = string.unpack("<I4", root, 5)
    assert(metadata % 4 == 0 and metadata >= 0x08000000
           and metadata + 504 <= 0x10000000, "Invalid manager metadata pointer")
    capture_bytes("manager-metadata.bin", read(metadata, 504))
    if os.getenv("ORAS_OBJECT_MANAGER_REFERENCES") == "1" then
        local manager_base = table_address - 0x722D0
        local references = search(read, 0x08000000, 0x10000000,
                                  string.pack("<I4", manager_base), 0x100000)
        local output = assert(io.open(capture .. "/manager-backrefs.txt", "w"))
        local records = {}
        local main_path = ""
        for character in ("data:/main"):gmatch(".") do main_path = main_path .. character .. "\0" end
        for index, address in ipairs(references) do
            assert(address % 4 == 0, "Unaligned manager reference")
            local start = math.max(0x08000000, address - 256)
            local length = math.min(320, 0x10000000 - start)
            local bytes = read(start, length)
            assert(string.unpack("<I4", bytes, address-start+1) == manager_base,
                   "Manager reference changed during scan")
            capture_bytes(string.format("manager-backref-%02d.bin", index), bytes)
            output:write(string.format("0x%08X 0x%08X %d\n", address, start, length))
            local offset = address-start+1
            if offset+35 <= #bytes and string.unpack("<I4", bytes, offset+8) == 0x76000
               and bytes:sub(offset+16, offset+35) == main_path then
                records[#records+1] = address
            end
        end
        output:close()
        local candidates = assert(io.open(capture .. "/save-records.txt", "w"))
        local referrers = assert(io.open(capture .. "/save-record-referrers.txt", "w"))
        local index = 0
        for _, record in ipairs(records) do
            candidates:write(string.format("0x%08X\n", record))
            local matches = search(read, 0x08000000, 0x10000000, string.pack("<I4", record), 0x100000)
            for _, address in ipairs(matches) do
                assert(address % 4 == 0, "Unaligned save-record reference")
                index = index + 1
                local start = math.max(0x08000000, address - 256)
                local length = math.min(512, 0x10000000 - start)
                local bytes = read(start, length)
                assert(string.unpack("<I4", bytes, address-start+1) == record,
                       "Save-record reference changed during scan")
                capture_bytes(string.format("save-record-referrer-%02d.bin", index), bytes)
                referrers:write(string.format("0x%08X 0x%08X 0x%08X %d\n", record, address, start, length))
            end
        end
        candidates:close(); referrers:close()
    end
end
journal:close()
local output = assert(io.open(capture .. "/matches.txt", "w"))
for _, address in ipairs(matches) do output:write(string.format("0x%08X\n", address)) end
output:close()
local done = assert(io.open(capture .. "/complete", "w")); done:write("read-only\n"); done:close()
