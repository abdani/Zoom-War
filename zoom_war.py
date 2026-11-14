"""
zoom_war.py — keeps trying to join a Zoom meeting until a slot opens (like a ticket war).

Usage (Windows, with the Zoom desktop app installed):
    python zoom_war.py "https://zoom.us/j/81234567890?pwd=xxxx" --name "Your Name"
    python zoom_war.py                      -> asks you to paste the link
    python zoom_war.py --calibrate          -> watch Zoom's windows (see below)

Guard mode is on by default: once in, the script keeps watching and joins again
automatically if you get dropped. Turn it off with --no-guard.

Needs one library to click through the preview screen:  pip install pywinauto
"""

import argparse
import atexit
import ctypes
import ctypes.wintypes as wt
import os
import re
import sys
import threading
import time
from datetime import datetime
from urllib.parse import parse_qs, quote, urlencode, urlparse

# ---------------------------------------------------------------------------
# PENANDA "BERHASIL MASUK" — sesuaikan dengan hasil mode --kalibrasi bila perlu
# ---------------------------------------------------------------------------
SUKSES_KELAS = ["ConfMultiTabContentWndClass"]          # kelas jendela meeting
SUKSES_JUDUL = ["Zoom Meeting", "Zoom Webinar", "Rapat Zoom"]
RUANG_TUNGGU = ["Waiting Room", "Ruang Tunggu", "waiting for the host",
                "menunggu host"]                         # dianggap dapat slot juga
SEDANG_KONEK = ["Connecting", "Menghubungkan"]           # jangan ditutup, tunggu
PREVIEW_KELAS = ["VideoPreviewWndClass", "VideoPreviewFitPanelClass"]  # bukan sukses!
GAGAL_KELAS = ["zJoinMeetingFailedDlgClass"]             # dialog gagal join (penuh)


# ---------------------------------------------------------------------------
# 1. Baca link undangan
# ---------------------------------------------------------------------------
def parse_link(link: str):
    """-> (host, confno, extra); extra = pwd/tk dari link (tk: token webinar terdaftar)."""
    link = link.strip().strip('"').strip("'")
    u = urlparse(link)
    id_ = r"(?<!\d)(\d{9,11})(?!\d)"        # tepat 9-11 digit, bukan potongan angka panjang
    # cadangan "ID saja" (mis. "812 3456 7890"); query dibuang supaya angka passcode
    # tidak dikira Meeting ID
    m = re.search(r"/(?:j|w|wc/join|wc|s)/" + id_, u.path) or \
        re.search(id_, link.split("?")[0].replace(" ", ""))
    if not m:
        raise ValueError("No meeting ID found in the link.")
    qs = parse_qs(u.query)
    extra = {k: qs[k][0] for k in ("pwd", "tk") if k in qs}
    host = u.netloc or "zoom.us"            # mis. us06web.zoom.us tetap dipakai
    if host.startswith("app."):             # link web client -> host biasa
        host = "zoom.us"
    return host, m.group(1), extra


def build_zoommtg(host, confno, extra, nama):
    q = {"action": "join", "confno": confno, **extra}
    if nama:
        q["uname"] = nama
    return f"zoommtg://{host}/join?{urlencode(q, quote_via=quote)}"


# ---------------------------------------------------------------------------
# 2. Intip jendela-jendela milik Zoom.exe (Windows API via ctypes)
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wt.HANDLE   # default c_int memotong handle 64-bit
    import winsound

WM_CLOSE = 0x0010


def _nama_proses(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        n = wt.DWORD(260)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(h)


def jendela_zoom(semua=False):
    """List (hwnd, judul, kelas) jendela Zoom; semua=True ikut jendela tersembunyi."""
    hasil, proses = [], {}                  # proses: cache pid -> nama, per pemindaian

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        if semua or user32.IsWindowVisible(hwnd):
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in proses:
                proses[pid.value] = _nama_proses(pid.value)
            if proses[pid.value] == "zoom.exe":
                t = ctypes.create_unicode_buffer(512)
                c = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, t, 512)
                user32.GetClassNameW(hwnd, c, 256)
                hasil.append((hwnd, t.value, c.value))
        return True

    user32.EnumWindows(cb, 0)
    return hasil


def _cocok(teks, daftar):
    teks = teks.lower()
    return any(d.lower() in teks for d in daftar)


def _sukses(judul, kelas):
    return kelas not in PREVIEW_KELAS and (
        kelas in SUKSES_KELAS or _cocok(judul, SUKSES_JUDUL))


def cek_status():
    """'penuh' | 'masuk' | 'tunggu' | 'preview' | 'konek' | 'gagal', plus hwnd."""
    wins = jendela_zoom()
    aturan = [                              # urutan = prioritas
        ("penuh", lambda j, k: k in GAGAL_KELAS),
        ("masuk", _sukses),
        ("preview", lambda j, k: k == PREVIEW_KELAS[0]),  # jendela preview yang punya tombol
        ("tunggu", lambda j, k: _cocok(j, RUANG_TUNGGU)),
        ("konek", lambda j, k: _cocok(j, SEDANG_KONEK)),
    ]
    for status, cocok in aturan:
        for hwnd, judul, kelas in wins:
            if cocok(judul, kelas):
                return status, hwnd
    return "gagal", None


# Nama tombol di jendela preview (UI Automation). Sesuaikan jika log menampilkan
# nama lain. Nama tombol = aksi yang AKAN dilakukan, mis. "Mute" berarti mic masih nyala.
TOMBOL_MIC_OFF = r"^mute\b|turn off (my )?(mic|microphone|audio)|matikan (mik|suara)"
TOMBOL_CAM_OFF = r"stop (my )?video|turn off (my )?(video|camera)|matikan (video|kamera)"
TOMBOL_JOIN = r"^(join|gabung|bergabung)$"


def klik_preview(hwnd):
    """Matikan mic & kamera lalu klik Join di jendela preview. True jika Join diklik."""
    try:
        from pywinauto import Desktop
    except ImportError:
        log("pywinauto is not installed. Run:  pip install pywinauto", "warn")
        return False

    def tekan(el):
        try:
            el.invoke()
        except Exception:
            el.click_input()               # cadangan: klik mouse sungguhan

    try:
        win = Desktop(backend="uia").window(handle=hwnd)
        tombol = [(el, (el.window_text() or "").strip())
                  for el in win.descendants()
                  if el.element_info.control_type in ("Button", "CheckBox")]
        for el, nama in tombol:
            n = nama.lower()
            # checkbox "Turn off my video" tidak berganti nama; jika sudah dicentang,
            # klik lagi justru menyalakan kamera
            if el.element_info.control_type == "CheckBox" and el.get_toggle_state() == 1:
                continue
            if re.search(TOMBOL_MIC_OFF, n) or re.search(TOMBOL_CAM_OFF, n):
                log(f"Clicking '{nama}'", "act")
                tekan(el)
        for el, nama in tombol:
            if re.search(TOMBOL_JOIN, nama.lower()):
                log(f"Clicking '{nama}'", "act")
                tekan(el)
                return True
        log(f"Join button not found. Visible buttons: {[n for _, n in tombol]}", "warn")
    except Exception as e:
        log(f"Could not read the preview window: {e}", "warn")
    return False


def tutup_dialog_zoom():
    """Tutup dialog Zoom sisa percobaan gagal (mis. 'meeting penuh')."""
    for hwnd, judul, kelas in jendela_zoom():
        if kelas in GAGAL_KELAS:           # jendela lain (tray, notifikasi) dibiarkan
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


# ---------------------------------------------------------------------------
# 3. Look: banner, colors, panels, a live status line. 24-bit ANSI colors in the
#    Windows console; plain text when output isn't a console (pipe, file, tests).
# ---------------------------------------------------------------------------
ANSI = False
BLUE, CYAN, RED, ORANGE = (45, 140, 255), (90, 210, 255), (235, 60, 60), (255, 150, 60)
GREEN, YELLOW, GREY, WHITE = (70, 215, 130), (255, 200, 70), (125, 132, 150), (235, 238, 245)
WIDTH = 64
KINDS = {"info": ("•", GREY, WHITE), "try": ("►", BLUE, WHITE), "act": ("»", CYAN, WHITE),
         "ok": ("■", GREEN, GREEN), "warn": ("!", YELLOW, YELLOW), "err": ("x", RED, RED)}
LETTERS = {  # 3-row block font for the banner
    "Z": ["▀▀█", "▄▀ ", "█▄▄"], "O": ["█▀█", "█ █", "█▄█"], "M": ["█▀▄▀█", "█ ▀ █", "█   █"],
    "W": ["█   █", "█ █ █", "▀▄▀▄▀"], "A": ["█▀█", "█▀█", "█ █"], "R": ["█▀█", "█▀▄", "█ █"], " ": ["  "] * 3,
}


def setup_console():
    """Turn on ANSI colors (VT processing) when stdout is a real console."""
    global ANSI
    if not sys.stdout.isatty():
        return
    h, mode = kernel32.GetStdHandle(-11), wt.DWORD()   # STD_OUTPUT_HANDLE
    ANSI = bool(kernel32.GetConsoleMode(h, ctypes.byref(mode))
                and kernel32.SetConsoleMode(h, mode.value | 0x4))   # ENABLE_VIRTUAL_TERMINAL_PROCESSING


def paint(text, rgb=None, bold=False, dim=False):
    if not ANSI:
        return text
    codes = (["1"] if bold else []) + (["2"] if dim else []) + ([f"38;2;{rgb[0]};{rgb[1]};{rgb[2]}"] if rgb else [])
    return f"\x1b[{';'.join(codes)}m{text}\x1b[0m" if codes else text


def visible_len(text):
    return len(re.sub(r"\x1b\[[0-9;]*m", "", text))


def _blend(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def banner():
    word = "ZOOM WAR"
    rows = [" ".join(LETTERS[ch][r] for ch in word) for r in range(3)]
    split = len(" ".join(LETTERS[ch][0] for ch in "ZOOM"))
    print()
    for row in rows:
        out = []
        for i, ch in enumerate(row):  # ZOOM: blue -> cyan, WAR: red -> orange (the icon's lightning)
            t = i / max(1, split) if i < split else (i - split) / max(1, len(row) - split)
            out.append(paint(ch, _blend(BLUE, CYAN, t) if i < split else _blend(RED, ORANGE, t), bold=True))
        print("   " + "".join(out))
    print("   " + paint("keeps trying until you're in", GREY) + paint("  ·  ", GREY, dim=True)
          + paint("Ctrl+C to stop", GREY, dim=True))
    print("   " + paint("─" * (WIDTH - 3), GREY, dim=True))


def panel(title, rows, color=BLUE):
    """Framed box: title in the top border, rows of (label, value)."""
    inner = WIDTH - 4
    head = f"─ {title} " if title else ""
    print("  " + paint("┌" + head + "─" * (inner - len(head)) + "┐", color))
    for label, value in rows:
        text = f" {paint(f'{label:<10}', GREY)}{value}" if label else f" {value}"
        print("  " + paint("│", color) + text + " " * max(0, inner - visible_len(text)) + paint("│", color))
    print("  " + paint("└" + "─" * inner + "┘", color))


def fmt_id(confno):
    """Meeting ID grouped like Zoom shows it: 812 3456 7890 / 123 456 7890 / 123 456 789."""
    cuts = {11: (3, 7), 10: (3, 6)}.get(len(confno), (3, 6))
    return f"{confno[:cuts[0]]} {confno[cuts[0]:cuts[1]]} {confno[cuts[1]:]}"


def fmt_dur(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m {s:02d}s" if m else f"{s}s"


def live(text):
    """One live line that is rewritten in place (spinner, countdown); console only."""
    if ANSI:
        print(f"\r\x1b[2K   {text}", end="", flush=True)


def title(text):
    if sys.platform == "win32":
        kernel32.SetConsoleTitleW(f"Zoom War · {text}" if text else "Zoom War")


def ask(label):
    return input(f"   {paint('►', RED, bold=True)} {paint(label, WHITE, bold=True)} ")


def log(pesan, kind="info"):
    sym, sym_color, text_color = KINDS[kind]
    lead = "\r\x1b[2K" if ANSI else ""                   # wipe the status line first
    print(f"{lead}   {paint(f'{datetime.now():%H:%M:%S}', GREY, dim=True)} "
          f"{paint(sym, sym_color, bold=True)} {paint(pesan, text_color)}", flush=True)


def alarm(hwnd, pesan):
    if hwnd:
        user32.ShowWindow(hwnd, 9)          # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    for _ in range(3):
        winsound.Beep(1200, 400)
        winsound.Beep(900, 400)
    # info + topmost; di thread terpisah supaya mode jaga tetap memantau
    threading.Thread(target=user32.MessageBoxW,
                     args=(None, pesan, "Zoom War", 0x40 | 0x40000), daemon=True).start()


# ---------------------------------------------------------------------------
# 4. Mode kalibrasi: tampilkan jendela Zoom yang muncul/berubah
# ---------------------------------------------------------------------------
def kalibrasi():
    log("Calibration mode. Join a Zoom meeting by hand and watch the list below.")
    log("Note the title/class when the meeting is full and when you got in. Ctrl+C to quit.")
    terakhir = set()
    try:
        while True:
            sekarang = {(j, k) for _, j, k in jendela_zoom()}
            for judul, kelas in sorted(sekarang - terakhir):
                log(f"SHOWN  title={judul!r:45} class={kelas!r}", "ok")
            for judul, kelas in sorted(terakhir - sekarang):
                log(f"GONE   title={judul!r:45} class={kelas!r}", "warn")
            terakhir = sekarang
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# 5. Loop utama
# ---------------------------------------------------------------------------
SPIN = "|/-\\"
STATUS_TEXT = {"konek": "connecting", "preview": "on the preview screen", "gagal": "waiting for Zoom"}


def menang(hwnd, judul, pesan, percobaan, mulai):
    """The win: big green panel, window title, alarm."""
    title(judul)
    print("\r\x1b[2K" if ANSI else "", end="")
    panel(None, [("", paint(f"■  {judul.upper()}", GREEN, bold=True)),
                 ("", paint(f"after {percobaan} attempt{'s' * (percobaan != 1)} · {fmt_dur(time.time() - mulai)}", GREY))],
          GREEN)
    alarm(hwnd, pesan)


def war(url, jeda, tunggu, batas_menit):
    mulai = time.time()
    percobaan = 0
    sudah_peringatan = False
    while time.time() - mulai < batas_menit * 60:
        percobaan += 1
        title(f"attempt #{percobaan}")
        log(f"Attempt #{percobaan}", "try")
        try:
            os.startfile(url)
        except OSError:
            sys.exit("Could not open Zoom. Make sure the Zoom desktop app is installed.")

        t0 = time.time()
        batas_tunggu = t0 + tunggu
        batas_keras = t0 + tunggu * 4   # preview/konek tak boleh menggantung selamanya
        klik_ke, klik_berikut, putar = 0, 0.0, 0
        while time.time() < batas_tunggu:
            status, hwnd = cek_status()
            if status == "penuh":
                break                          # langsung coba lagi, tak perlu menunggu
            if status == "preview" and klik_ke < 3 and time.time() >= klik_berikut:
                # diulang maks 3x: tombol sering belum dirender saat jendela baru muncul
                klik_ke, klik_berikut = klik_ke + 1, time.time() + 2
                if klik_preview(hwnd):
                    klik_ke = 3
                elif klik_ke == 3 and not sudah_peringatan:
                    log("Auto-click failed, please click Join yourself (see the log above).", "warn")
                    sudah_peringatan = True
            if status in ("preview", "konek"):  # tunggu proses join selesai
                batas_tunggu = min(batas_keras, max(batas_tunggu, time.time() + 3))
            if status == "masuk":
                menang(hwnd, "You're in the meeting", "You joined the Zoom meeting.", percobaan, mulai)
                return True
            if status == "tunggu":
                menang(hwnd, "In the waiting room", "You are in the Zoom waiting room. Don't close it.",
                       percobaan, mulai)
                return True
            putar += 1
            status_text = STATUS_TEXT.get(status, status)
            live(paint(SPIN[putar % 4], CYAN, bold=True) + paint(f"  {status_text}  ", WHITE)
                   + paint(f"{time.time() - t0:4.1f}s", GREY))
            time.sleep(0.2)

        log("Not in yet, probably full", "warn")
        tutup_dialog_zoom()
        for sisa in range(jeda, 0, -1):         # countdown bar to the next attempt
            isi = round((jeda - sisa) / jeda * 20)
            live(paint("next attempt in ", GREY) + paint(f"{sisa}s ", WHITE, bold=True)
                   + paint("▓" * isi, BLUE) + paint("░" * (20 - isi), GREY, dim=True)
                   + paint(f"   running {fmt_dur(time.time() - mulai)}", GREY, dim=True))
            time.sleep(1)

    title("time limit reached")
    log(f"Time limit of {batas_menit} minutes reached, stopping.", "err")
    return False


def masih_di_meeting():
    # Jendela meeting dicek termasuk yang tersembunyi, supaya Zoom yang
    # di-minimize tidak dikira sudah keluar.
    if any(k in SUKSES_KELAS for _, _, k in jendela_zoom(semua=True)):
        return True
    return cek_status()[0] in ("masuk", "tunggu")


def jaga(toleransi=3, interval=2):
    """Pantau meeting; kembali (untuk war ulang) jika terlempar keluar."""
    log("Guard mode on: watching the meeting", "act")
    title("in the meeting · guarding")
    hilang, sejak = 0, time.time()
    while True:
        hilang = 0 if masih_di_meeting() else hilang + 1
        if hilang >= toleransi:            # ~6 detik berturut-turut di luar meeting
            log("Dropped out of the meeting. Joining again...", "err")
            return
        live(paint("● ", GREEN, bold=True) + paint("in the meeting ", WHITE)
               + paint(fmt_dur(time.time() - sejak), GREY) + paint("   guard mode on", GREY, dim=True))
        time.sleep(interval)


def main():
    if sys.platform != "win32":
        sys.exit("This script runs on Windows only.")

    ap = argparse.ArgumentParser(description="Join a Zoom meeting automatically as soon as a slot opens.")
    ap.add_argument("link", nargs="?", help="Zoom invite link")
    ap.add_argument("--name", dest="nama", default="", metavar="NAME", help="Your display name in Zoom")
    ap.add_argument("--delay", dest="jeda", type=int, default=5, metavar="SECONDS",
                    help="Seconds between attempts (default 5, min 5)")
    ap.add_argument("--wait", dest="tunggu", type=int, default=15, metavar="SECONDS",
                    help="Seconds to wait for the result of each attempt (default 15)")
    ap.add_argument("--limit", dest="batas", type=int, default=120, metavar="MINUTES",
                    help="Total minutes to keep trying (default 120)")
    ap.add_argument("--no-guard", dest="tanpa_jaga", action="store_true",
                    help="Turn off guard mode (default: join again if you get dropped)")
    ap.add_argument("--calibrate", dest="kalibrasi", action="store_true",
                    help="Show Zoom's windows as they appear, to tune the markers")
    # The old Indonesian flags keep working, hidden from --help.
    for old, dest, kw in (("--nama", "nama", {}), ("--jeda", "jeda", {"type": int}),
                          ("--tunggu", "tunggu", {"type": int}), ("--batas", "batas", {"type": int}),
                          ("--tanpa-jaga", "tanpa_jaga", {"action": "store_true"}),
                          ("--kalibrasi", "kalibrasi", {"action": "store_true"})):
        ap.add_argument(old, dest=dest, help=argparse.SUPPRESS, default=argparse.SUPPRESS, **kw)
    a = ap.parse_args()

    banner()
    if a.kalibrasi:
        kalibrasi()
        return

    link = a.link
    while True:
        link = link or ask("Paste the Zoom invite link:")
        try:
            host, confno, extra = parse_link(link)
            break
        except ValueError:
            log("That doesn't look like a Zoom link or meeting ID, try again.", "warn")
            link = ""
    nama = a.nama
    if not nama:
        print("\n   " + paint("Your name in Zoom", WHITE, bold=True))
        print(f"     {paint('1', CYAN, bold=True)}  Use your Zoom account's default name")
        print(f"     {paint('2', CYAN, bold=True)}  Type a new name")
        while (pilih := ask("Choose 1 or 2:").strip()) not in ("1", "2"):
            log("Type 1 or 2.", "warn")
        while pilih == "2" and not nama:
            nama = ask("Name:").strip()
    if len(nama) > 64:
        log(f"The name has {len(nama)} characters, more than 64; Zoom may cut it.", "warn")
    url = build_zoommtg(host, confno, extra, nama)
    yes, no = paint("yes", GREEN), paint("no", GREY)
    print()
    panel("Meeting", [("ID", paint(fmt_id(confno), WHITE, bold=True)),
                      ("Passcode", yes if "pwd" in extra else no),
                      *([("Webinar", paint("registration token", GREEN))] if "tk" in extra else []),
                      ("Host", host),
                      ("Name", (nama[:40] + "…" if len(nama) > 41 else nama) or paint("your Zoom account's name", GREY)),
                      ("Retry", f"every {max(5, a.jeda)}s · wait {a.tunggu}s · stop after {a.batas} min"),
                      ("Guard", paint("off", GREY) if a.tanpa_jaga else paint("on", GREEN) + paint("  (rejoins if dropped)", GREY))])
    print()
    # cegah laptop sleep / layar mati selama war (otomatis lepas saat script selesai)
    kernel32.SetThreadExecutionState(0x80000000 | 0x1 | 0x2)

    while war(url, max(5, a.jeda), a.tunggu, a.batas) and not a.tanpa_jaga:
        jaga()


def set_console_icon():
    """Zoom War's icon + title on the console window (title bar and taskbar).
    Classic console only: Windows Terminal ignores app icons (zoom_war.bat reopens there in conhost)."""
    kernel32.SetConsoleTitleW("Zoom War")
    hwnd = kernel32.GetConsoleWindow()
    ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zoom_war.ico")
    if not hwnd or not os.path.exists(ico):
        return
    user32.LoadImageW.restype = wt.HANDLE
    user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
    user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    for which, metric in ((1, 11), (0, 49)):    # ICON_BIG / SM_CXICON, ICON_SMALL / SM_CXSMICON
        size = user32.GetSystemMetrics(metric)
        h = user32.LoadImageW(None, ico, 1, size, size, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
        if h:
            user32.SendMessageW(hwnd, 0x80, which, h)          # WM_SETICON


def _tahan_jendela():
    try:
        input("\n   " + paint("Press Enter to close...", GREY))
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    if len(sys.argv) == 1:                 # dibuka dengan double-click: jangan langsung tutup.
        atexit.register(_tahan_jendela)    # atexit jalan SETELAH pesan error/traceback tercetak
    if sys.platform == "win32":
        set_console_icon()
        setup_console()
    try:
        main()
    except (KeyboardInterrupt, EOFError):  # EOF: input ditutup (Ctrl+Z / pipe kosong)
        title("stopped")
        log("Stopped.", "warn")
