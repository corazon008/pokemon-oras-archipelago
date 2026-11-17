-- Native controller actions in an isolated profile; no game memory API calls.
local plan_path = assert(os.getenv("ORAS_UI_PLAN"))
local capture = assert(os.getenv("ORAS_UI_CAPTURE"))
local speed = tonumber(os.getenv("ORAS_UI_SPEED") or "100")
assert(speed and speed >= 1 and speed <= 1000 and speed % 1 == 0)
if speed ~= 100 then client.speedmode(speed) end
local allowed = {
    A=true, B=true, X=true, Y=true, Up=true, Down=true, Left=true, Right=true,
    L=true, R=true, Start=true, Select=true,
}
local buttons = joypad.get()
local steps = {}
local total_frames = 0
for line in io.lines(plan_path) do
    local count, names = line:match("^(%d+):([%a+%-]+)$")
    count = tonumber(count)
    assert(count and count >= 1 and count <= 3600, "Invalid UI step")
    local controls = {}
    for name, state in pairs(buttons) do
        if type(state) == "boolean" then controls[name] = false end
    end
    if names ~= "-" then
        for name in names:gmatch("[^+]+") do
            assert(allowed[name] and buttons[name] ~= nil, "Unsupported button: " .. name)
            controls[name] = true
        end
    end
    total_frames = total_frames + count
    assert(total_frames <= 30000, "UI plan too long")
    steps[#steps + 1] = {count=count, controls=controls, names=names}
end
assert(#steps > 0, "Empty UI plan")
for index, step in ipairs(steps) do
    for frame = 1, step.count do
        joypad.set(step.controls)
        emu.frameadvance()
    end
    client.screenshot(string.format("%s/step-%02d.png", capture, index))
    print(string.format("ORAS_UI_STEP %d frames=%d buttons=%s", index, step.count, step.names))
    if type(ORAS_UI_AFTER_STEP) == "function" then ORAS_UI_AFTER_STEP(index) end
end
local complete = assert(io.open(capture .. "/complete", "w"))
complete:write(tostring(emu.framecount()), "\n")
complete:close()
if os.getenv("ORAS_UI_CONTINUE") == "1" then return end
client.exit()
