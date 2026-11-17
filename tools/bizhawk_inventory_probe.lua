-- Explicit read-only candidate observation after native UI boot.
local ui_script = assert(os.getenv("ORAS_UI_SCRIPT"))
local capture = assert(os.getenv("ORAS_UI_CAPTURE"))
assert(os.getenv("ORAS_UI_CONTINUE") == "1")
local address = assert(tonumber(os.getenv("ORAS_INVENTORY_ADDRESS")))
local length = assert(tonumber(os.getenv("ORAS_INVENTORY_LENGTH")))
assert(length == 0xB90, "Unexpected inventory observation length")
local journal = assert(io.open(capture .. "/inventory-read-requests.txt", "w"))

local function sample(name)
    journal:write(name, "\n")
    journal:flush()
    local bytes = memory.read_bytes_as_array(address, length, "System Bus")
    local output = {}
    for _, byte in ipairs(bytes) do output[#output + 1] = string.char(byte) end
    assert(#output == length, "Incomplete inventory read")
    local file = assert(io.open(capture .. "/" .. name .. ".bin", "wb"))
    file:write(table.concat(output))
    file:close()
    print("ORAS_INVENTORY_READ " .. name .. " " .. tostring(length))
end
local sample_step = tonumber(os.getenv("ORAS_INVENTORY_SAMPLE_STEP") or "")
if sample_step then
    ORAS_UI_AFTER_STEP = function(index)
        if index == sample_step then sample("inventory-before") end
    end
end
dofile(ui_script)
sample("inventory-read")
journal:close()
client.exit()
