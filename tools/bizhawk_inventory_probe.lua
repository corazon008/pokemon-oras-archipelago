-- Explicit read-only candidate observation after native UI boot.
local ui_script = assert(os.getenv("ORAS_UI_SCRIPT"))
local capture = assert(os.getenv("ORAS_UI_CAPTURE"))
assert(os.getenv("ORAS_UI_CONTINUE") == "1")
dofile(ui_script)

local address = assert(tonumber(os.getenv("ORAS_INVENTORY_ADDRESS")))
local length = assert(tonumber(os.getenv("ORAS_INVENTORY_LENGTH")))
assert(length == 0xB90, "Unexpected inventory observation length")
local requested = assert(io.open(capture .. "/inventory-requested", "w"))
requested:write("1\n")
requested:close()

local bytes = memory.read_bytes_as_array(address, length, "System Bus")
local output = {}
for _, byte in ipairs(bytes) do output[#output + 1] = string.char(byte) end
assert(#output == length, "Incomplete inventory read")
local file = assert(io.open(capture .. "/inventory-read.bin", "wb"))
file:write(table.concat(output))
file:close()
print("ORAS_INVENTORY_READ " .. tostring(length))
client.exit()
