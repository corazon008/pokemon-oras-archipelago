-- Frame-level read-only sampling. Host capture writes only; no game-memory writes.
return function(config, read)
    assert(config.schema_version == 1)
    assert(type(config.ranges) == "table" and #config.ranges >= 1 and #config.ranges <= 12)
    assert(config.max_ticks >= 1 and config.max_ticks <= 4000)
    local function load(path, limit)
        local file = io.open(path, "rb")
        if not file then return nil end
        local bytes = file:read(limit + 1) or ""; file:close()
        assert(#bytes <= limit, "Capture source exceeds bound")
        return bytes
    end
    local function store(path, bytes)
        local file = assert(io.open(path, "wb"))
        file:write(bytes); file:close()
    end
    local timeline = assert(io.open(config.capture .. "/timeline.tsv", "w"))
    local requests = assert(io.open(config.capture .. "/reads.tsv", "w"))
    local states, seen_names = {}, {}
    for _, range in ipairs(config.ranges) do
        assert(type(range.name) == "string" and range.name:match("^[a-z][a-z0-9_]*$"))
        assert(not seen_names[range.name], "Duplicate sample range")
        seen_names[range.name] = true
        assert(range.address % 4 == 0 and range.address >= 0x08000000)
        assert(range.length >= 1 and range.length <= 16384 and range.address + range.length <= 0x10000000)
        if range.stable_prefix then
            assert(range.stable_prefix >= 1 and range.stable_prefix <= range.length)
            assert(range.reference_path)
        end
        local reference = range.reference_path and assert(load(range.reference_path, range.length))
        if reference then assert(#reference == range.length) end
        states[#states+1] = {range=range, version=0, reference=reference}
    end
    local ticks, last_frame, file_version, last_file, closed = 0, nil, 0, nil, false
    local observer = {}
    function observer.tick(frame, step)
        assert(not closed and type(frame) == "number" and frame % 1 == 0)
        assert(not last_frame or frame == last_frame + 1, "Nonconsecutive observer frames")
        ticks = ticks + 1
        assert(ticks <= config.max_ticks, "Native-save observation exceeded frame bound")
        last_frame = frame
        local row = {frame, step}
        for _, state in ipairs(states) do
            local range = state.range
            requests:write(string.format("%d\t0x%08X\t%d\n", frame, range.address, range.length))
            local bytes = read(range.address, range.length)
            assert(type(bytes) == "string" and #bytes == range.length, "Incomplete observer read")
            if state.reference and ticks == 1 then
                assert(bytes == state.reference, "Initial observation reference mismatch")
            end
            if range.stable_prefix then
                assert(bytes:sub(1, range.stable_prefix) == state.reference:sub(1, range.stable_prefix),
                       "Stable object/header changed during native save")
            end
            if bytes ~= state.last then
                state.version = state.version + 1
                store(string.format("%s/%s-%04d.bin", config.capture, range.name, state.version), bytes)
                state.last = bytes
            end
            row[#row+1] = state.version
        end
        local save = load(config.save_path, 0x76000)
        if save ~= last_file or ticks == 1 then
            file_version = file_version + 1
            if save then store(string.format("%s/file-%04d.bin", config.capture, file_version), save) end
            last_file = save
        end
        row[#row+1] = file_version
        row[#row+1] = save and #save or -1
        timeline:write(table.concat(row, "\t"), "\n")
        timeline:flush(); requests:flush()
    end
    function observer.finish()
        assert(not closed and ticks > 0)
        timeline:close(); requests:close()
        store(config.capture .. "/observation-complete", tostring(ticks) .. "\n")
        closed = true
    end
    return observer
end
