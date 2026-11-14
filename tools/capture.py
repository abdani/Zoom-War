"""README screenshot + icon check: opens zoom_war.bat the way a double-click does, waits for the
classic console window, checks that it carries the Zoom War icon, pastes a demo link and grabs
the window at the name menu (no Zoom meeting is ever started).
usage (from the repo root): python tools/capture.py   -> docs/images/console.png"""
import ctypes
import os
import subprocess
import time
from ctypes import wintypes as wt

from PIL import Image
from pywinauto import Application

user32, gdi = ctypes.windll.user32, ctypes.windll.gdi32
ctypes.windll.shcore.SetProcessDpiAwareness(1)
user32.SendMessageW.restype = ctypes.c_void_p
DEMO_LINK = "https://us06web.zoom.us/j/81234567890?pwd=demo"  # made-up meeting
FONT_STEP = 1            # px wider glyphs than the console default, for a more readable screenshot
WINDOW = (960, 318)      # size after the font change: just tall enough for the name menu


class COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class CONSOLE_FONT_INFOEX(ctypes.Structure):
    _fields_ = [("cbSize", wt.ULONG), ("nFont", wt.DWORD), ("dwFontSize", COORD),
                ("FontFamily", wt.UINT), ("FontWeight", wt.UINT), ("FaceName", wt.WCHAR * 32)]


def bigger_font(pid, step):
    """Grow the font of the console that process `pid` runs in (that window only)."""
    k = ctypes.windll.kernel32
    k.CreateFileW.restype = wt.HANDLE
    k.FreeConsole()
    if not k.AttachConsole(pid):
        raise OSError("AttachConsole failed")
    try:
        out = k.CreateFileW("CONOUT$", 0xC0000000, 3, None, 3, 0, None)  # GENERIC_RW, share RW, OPEN_EXISTING
        def font():
            f = CONSOLE_FONT_INFOEX(cbSize=ctypes.sizeof(CONSOLE_FONT_INFOEX))
            k.GetCurrentConsoleFontEx(out, False, ctypes.byref(f))
            return f
        info = font()
        w0, h0 = info.dwFontSize.X, info.dwFontSize.Y
        # The console sizes Consolas by cell height: +2 px height alone kept 8 px wide glyphs
        # (only the line spacing grew). Step up until the glyphs are `step` px wider.
        for h in range(h0 + 1, h0 + 12):
            info.dwFontSize = COORD(0, h)
            k.SetCurrentConsoleFontEx(out, False, ctypes.byref(info))
            if font().dwFontSize.X >= w0 + step:
                break
        now = font()
        k.CloseHandle(out)
        print(f"font {info.FaceName}: cell {w0}x{h0} -> {now.dwFontSize.X}x{now.dwFontSize.Y}")
    finally:
        k.FreeConsole()


def app_pid():
    """PID of the python.exe running zoom_war.py (the console's client, AttachConsole needs it)."""
    ps = "(Get-CimInstance Win32_Process | ? { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'zoom_war.py' }).ProcessId"
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.split()
    return int(out[0])


def find_console():
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        t, c = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(hwnd, t, 256)
        user32.GetClassNameW(hwnd, c, 64)
        if c.value == "ConsoleWindowClass" and "Zoom War" in t.value and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def grab(hwnd, path):
    r, vis = wt.RECT(), wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(vis), ctypes.sizeof(vis))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = user32.GetWindowDC(hwnd)
    mem, bmp = gdi.CreateCompatibleDC(hdc), gdi.CreateCompatibleBitmap(hdc, w, h)
    gdi.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, 2)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi.GetBitmapBits(bmp, len(buf), buf)
    im = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    im.crop((vis.left - r.left, vis.top - r.top, vis.right - r.left, vis.bottom - r.top)).save(path)
    gdi.DeleteObject(bmp), gdi.DeleteDC(mem), user32.ReleaseDC(hwnd, hdc)
    print(path, im.size)


def main():
    os.startfile(os.path.abspath("zoom_war.bat"))  # same as a double-click (default terminal first)
    end, hwnd = time.time() + 30, None
    while not hwnd and time.time() < end:
        time.sleep(0.3)
        hwnd = find_console()
    assert hwnd, "no classic console window titled 'Zoom War'"
    time.sleep(2)                                    # pip check + python start
    big, small = user32.SendMessageW(hwnd, 0x7F, 1, 0), user32.SendMessageW(hwnd, 0x7F, 0, 0)  # WM_GETICON
    assert big and small, "console window has no icon"
    print("icon set: big + small")
    bigger_font(app_pid(), FONT_STEP)
    time.sleep(0.3)
    user32.SetWindowPos(hwnd, None, 120, 80, *WINDOW, 0x4)  # SWP_NOZORDER
    win = Application(backend="win32").connect(handle=hwnd).window(handle=hwnd)
    win.set_focus()                                  # plain SetForegroundWindow is refused from a background process
    time.sleep(0.5)
    win.type_keys(DEMO_LINK + "{ENTER}", with_spaces=True, pause=0.01)
    time.sleep(1.5)
    os.makedirs("docs/images", exist_ok=True)
    grab(hwnd, "docs/images/console.png")
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    subprocess.run(["taskkill", "/PID", str(pid.value), "/T", "/F"], capture_output=True,  # never reaches the war
                   stdin=subprocess.DEVNULL)  # our own console was released by bigger_font()


if __name__ == "__main__":
    main()
