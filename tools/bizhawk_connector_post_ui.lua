-- Native buttons only, driven by frame-end events while upstream connector runs.
-- Signal is created only after Python verifies the full written inventory.
local plan = assert(os.getenv("ORAS_CONNECTOR_POST_PLAN"))
local capture = assert(os.getenv("ORAS_CONNECTOR_POST_CAPTURE"))
local signal = assert(os.getenv("ORAS_CONNECTOR_POST_SIGNAL"))
local allowed = {A=true, B=true, X=true, Y=true, Up=true, Down=true, Left=true,
                 Right=true, L=true, R=true, Start=true, Select=true}
local neutral = {}
for name, state in pairs(joypad.get()) do
    if type(state) == "boolean" then neutral[name] = false end
end
local steps, total = {}, 0
for line in io.lines(plan) do
    local count, names = line:match("^(%d+):([%a+%-]+)$")
    count = tonumber(count)
    assert(count and count >= 1 and count <= 3600, "Invalid post UI step")
    local controls = {}
    for name, state in pairs(neutral) do controls[name] = state end
    if names ~= "-" then
        for name in names:gmatch("[^+]+") do
            assert(allowed[name] and neutral[name] ~= nil, "Unsupported post UI button")
            controls[name] = true
        end
    end
    total = total + count
    assert(total <= 30000, "Post UI plan too long")
    steps[#steps + 1] = {count=count, controls=controls}
end
assert(#steps > 0, "Empty post UI plan")
local index, remaining, started, done = 1, 0, false, false
event.onframeend(function()
    if done then return end
    if not started then
        local file = io.open(signal, "r")
        if not file then return end
        file:close()
        started = true
    elseif remaining > 0 then
        remaining = remaining - 1
        if remaining == 0 then
            client.screenshot(string.format("%s/step-%02d.png", capture, index))
            index = index + 1
        end
    end
    if index > #steps then
        joypad.set(neutral)
        local file = assert(io.open(capture .. "/complete", "w"))
        file:write(tostring(emu.framecount()), "\n")
        file:close()
        done = true
    else
        if remaining == 0 then remaining = steps[index].count end
        joypad.set(steps[index].controls)
    end
end, "ORAS connector native post UI")
