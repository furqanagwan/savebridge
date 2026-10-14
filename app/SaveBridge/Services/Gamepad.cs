using System.Runtime.InteropServices;
using Microsoft.UI.Dispatching;

namespace SaveBridge.Services;

public enum PadButton { B, X, Y, LeftShoulder, RightShoulder, Menu, View }

/// <summary>
/// Controller support. WinUI 3 desktop apps don't receive controller input, so this
/// polls XInput while the app is in the foreground. Movement and A are sent to the
/// window as the gamepad keys XAML still understands (2D focus movement, invoke);
/// the triggers as Page Up/Down. The other buttons arrive in desktop XAML as plain
/// keyboard keys, so they are raised as <see cref="Button"/> for MainWindow to act
/// on (B = close or back, LB/RB = sections, Y = refresh, View = search, Menu = settings).
/// </summary>
public sealed class Gamepad
{
    public static Gamepad Instance { get; } = new();

    public bool Connected { get; private set; }
    public event EventHandler? ConnectedChanged;
    /// <summary>Set whenever a controller button is used; keyboard or mouse use clears it.</summary>
    public bool LastInputWasGamepad { get; set; }
    /// <summary>Right stick: scroll by this many pixels (negative = up).</summary>
    public event EventHandler<double>? Scroll;
    /// <summary>A button the app handles itself.</summary>
    public event EventHandler<PadButton>? Button;

    DispatcherQueueTimer? _timer;
    nint _hwnd;
    int _slot = -1;
    long _nextScan;
    ushort _held;
    int _dir = -1;
    long _repeatAt;

    const ushort DpadUp = 0x1, DpadDown = 0x2, DpadLeft = 0x4, DpadRight = 0x8;
    const ushort ButtonA = 0x1000;
    const ushort KeyGamepadA = 0xC3;
    static readonly (ushort Bit, PadButton Button)[] AppButtons =
    [
        (0x2000, PadButton.B),
        (0x4000, PadButton.X),
        (0x8000, PadButton.Y),
        (0x0100, PadButton.LeftShoulder),
        (0x0200, PadButton.RightShoulder),
        (0x0010, PadButton.Menu),
        (0x0020, PadButton.View),
    ];
    static readonly ushort[] DirectionKeys = [0xCB, 0xCC, 0xCD, 0xCE]; // GamepadDPadUp/Down/Left/Right
    const ushort LeftTrigger = 0x21, RightTrigger = 0x22;              // Page Up / Page Down
    bool _lt, _rt;

    public void Start(Microsoft.UI.Xaml.Window window)
    {
        _hwnd = WinRT.Interop.WindowNative.GetWindowHandle(window);
        _timer = DispatcherQueue.GetForCurrentThread().CreateTimer();
        _timer.Interval = TimeSpan.FromMilliseconds(16);
        _timer.Tick += (_, _) => Poll();
        _timer.Start();
    }

    void Poll()
    {
        var now = Environment.TickCount64;
        if (_slot < 0)
        {
            if (now < _nextScan) return;   // probing empty slots is slow; once a second is plenty
            _nextScan = now + 1000;
            for (var i = 0; i < 4 && _slot < 0; i++)
                if (XInputGetState(i, out _) == 0) _slot = i;
            if (_slot >= 0) SetConnected(true);
            return;
        }
        if (XInputGetState(_slot, out var state) != 0)
        {
            _slot = -1;
            _held = 0;
            SetConnected(false);
            return;
        }
        if (GetForegroundWindow() != _hwnd) { _held = state.Buttons; _dir = -1; return; }

        var pad = state;
        bool Pressed(ushort bit) => (pad.Buttons & bit) != 0 && (_held & bit) == 0;
        if (Pressed(ButtonA)) Press(KeyGamepadA);
        foreach (var (bit, button) in AppButtons)
            if (Pressed(bit))
            {
                LastInputWasGamepad = true;
                Button?.Invoke(this, button);
            }
        _held = pad.Buttons;

        var lt = pad.LeftTrigger > 120;
        var rt = pad.RightTrigger > 120;
        if (lt && !_lt) Press(LeftTrigger);
        if (rt && !_rt) Press(RightTrigger);
        _lt = lt; _rt = rt;

        // D-pad or left stick: one step, then repeat while held.
        var dir = Direction(pad);
        if (dir != _dir)
        {
            _dir = dir;
            if (dir >= 0) { Press(DirectionKeys[dir]); _repeatAt = now + 400; }
        }
        else if (dir >= 0 && now >= _repeatAt)
        {
            Press(DirectionKeys[dir]);
            _repeatAt = now + 110;
        }

        // Right stick scrolls the page.
        if (Math.Abs((int)pad.RightY) > 8000)
            Scroll?.Invoke(this, -pad.RightY / 32768.0 * 40);
    }

    static int Direction(XInputGamepad pad)
    {
        if ((pad.Buttons & DpadUp) != 0) return 0;
        if ((pad.Buttons & DpadDown) != 0) return 1;
        if ((pad.Buttons & DpadLeft) != 0) return 2;
        if ((pad.Buttons & DpadRight) != 0) return 3;
        const int dead = 16000;
        int x = pad.LeftX, y = pad.LeftY;
        if (Math.Abs(x) < dead && Math.Abs(y) < dead) return -1;
        return Math.Abs(y) >= Math.Abs(x) ? (y > 0 ? 0 : 1) : (x < 0 ? 2 : 3);
    }

    /// <summary>Sends a key to the focused window (used for Escape too).</summary>
    public void Press(ushort key)
    {
        LastInputWasGamepad = true;
        var input = new Input[2];
        input[0].Type = 1; input[0].Key.VirtualKey = key;
        input[1].Type = 1; input[1].Key.VirtualKey = key; input[1].Key.Flags = 2; // key up
        SendInput(2, input, Marshal.SizeOf<Input>());
    }

    void SetConnected(bool connected)
    {
        if (Connected == connected) return;
        Connected = connected;
        ConnectedChanged?.Invoke(this, EventArgs.Empty);
    }

    // ---- Win32 -------------------------------------------------------------------

    [StructLayout(LayoutKind.Sequential)]
    struct XInputGamepad
    {
        public ushort Buttons;
        public byte LeftTrigger, RightTrigger;
        public short LeftX, LeftY, RightX, RightY;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct XInputState
    {
        public uint Packet;
        public XInputGamepad Pad;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct KeyInput
    {
        public ushort VirtualKey, Scan;
        public uint Flags, Time;
        public nint Extra;
    }

    [StructLayout(LayoutKind.Explicit, Size = 40)]
    struct Input
    {
        [FieldOffset(0)] public uint Type;
        [FieldOffset(8)] public KeyInput Key;
    }

    static uint XInputGetState(int index, out XInputGamepad pad)
    {
        var r = XInputGetStateNative(index, out var s);
        pad = s.Pad;
        return r;
    }

    [DllImport("xinput1_4.dll", EntryPoint = "XInputGetState")]
    static extern uint XInputGetStateNative(int index, out XInputState state);

    [DllImport("user32.dll")]
    static extern uint SendInput(uint count, Input[] inputs, int size);

    [DllImport("user32.dll")]
    static extern nint GetForegroundWindow();
}
