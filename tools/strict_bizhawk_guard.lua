-- Fail-closed GUARD replacement for the pinned generic connector.
-- Factory is emulator-independent; all fallible decode/read work stays inside pcall.
return function(read, decode, in_domain)
    return function(request)
        local response = {type="GUARD_RESPONSE", address=0, value=false}
        local ok, matches = pcall(function()
            assert(type(request) == "table")
            local address = request.address
            assert(type(address) == "number" and address == math.floor(address))
            assert(address >= 0 and address <= 0xFFFFFFFF)
            response.address = address
            assert(type(request.domain) == "string" and #request.domain > 0)
            assert(type(request.expected_data) == "string")
            local expected = decode(request.expected_data)
            assert(type(expected) == "table")
            local size = #expected
            assert(size > 0 and size <= 0x10000, "Guard length outside probe limit")
            assert(address + size <= 0x100000000)
            assert(in_domain(address, size, request.domain), "Unknown domain or out-of-range guard")
            local actual = read(address, size, request.domain)
            assert(type(actual) == "table" and #actual == size, "Incomplete guard read")
            for index = 1, size do
                local byte, observed = expected[index], actual[index]
                assert(type(byte) == "number" and byte == math.floor(byte) and byte >= 0 and byte <= 255)
                assert(type(observed) == "number" and observed == math.floor(observed)
                       and observed >= 0 and observed <= 255)
                if byte ~= observed then return false end
            end
            return true
        end)
        response.value = ok and matches == true
        return response
    end
end
