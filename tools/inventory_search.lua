-- Exact byte-pattern search over bounded, read-only chunks.
-- No emulator API dependency; caller provides the read function.
return function(read, start_address, end_address, pattern, chunk_size)
    assert(#pattern >= 4 and #pattern % 4 == 0)
    assert(start_address >= 0 and end_address > start_address)
    assert(chunk_size >= #pattern)
    local anchor_offset, anchor
    for offset = 0, #pattern - 4, 4 do
        local candidate = pattern:sub(offset + 1, offset + 4)
        if candidate ~= "\0\0\0\0" then
            anchor_offset, anchor = offset, candidate
            break
        end
    end
    assert(anchor, "All-zero patterns are not accepted")
    local carry = ""
    local matches, seen = {}, {}
    local reads = 0
    for address = start_address, end_address - 1, chunk_size do
        local size = math.min(chunk_size, end_address - address)
        local bytes = read(address, size)
        reads = reads + 1
        assert(type(bytes) == "string" and #bytes == size, "Incomplete binary memory read")
        local window = carry .. bytes
        local base = address - #carry
        local cursor = 1
        while true do
            local found = window:find(anchor, cursor, true)
            if not found then break end
            local first = found - anchor_offset
            if first >= 1 and first + #pattern - 1 <= #window then
                local candidate_address = base + first - 1
                if not seen[candidate_address] and window:sub(first, first + #pattern - 1) == pattern then
                    matches[#matches + 1] = candidate_address
                    seen[candidate_address] = true
                    assert(#matches <= 16, "Too many inventory copies; observation is ambiguous")
                end
            end
            cursor = found + 1
        end
        carry = window:sub(math.max(1, #window - #pattern + 2))
    end
    return matches, reads
end
