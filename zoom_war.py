"""
zoom_war.py — keeps trying to join a Zoom meeting until a slot opens (like a ticket war).

Usage (Windows, with the Zoom desktop app installed):
    python zoom_war.py "https://zoom.us/j/81234567890?pwd=xxxx" --name "Abdani"
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
        log("pywinauto is not installed. Run:  pip install pywinauto")
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
                log(f"Clicking '{nama}'")
                tekan(el)
        for el, nama in tombol:
            if re.search(TOMBOL_JOIN, nama.lower()):
                log(f"Clicking '{nama}'")
                tekan(el)
                return True
        log(f"Join button not found. Visible buttons: {[n for _, n in tombol]}")
    except Exception as e:
        log(f"Could not read the preview window: {e}")
    return False


def tutup_dialog_zoom():
    """Tutup dialog Zoom sisa percobaan gagal (mis. 'meeting penuh')."""
    for hwnd, judul, kelas in jendela_zoom():
        if kelas in GAGAL_KELAS:           # jendela lain (tray, notifikasi) dibiarkan
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


# ---------------------------------------------------------------------------
# 3. Notifikasi
# ---------------------------------------------------------------------------
def log(pesan):
    print(f"[{datetime.now():%H:%M:%S}] {pesan}", flush=True)


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
                log(f"SHOWN  title={judul!r:45} class={kelas!r}")
            for judul, kelas in sorted(terakhir - sekarang):
                log(f"GONE   title={judul!r:45} class={kelas!r}")
            terakhir = sekarang
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# 5. Loop utama
# ---------------------------------------------------------------------------
def war(url, jeda, tunggu, batas_menit):
    mulai = time.time()
    percobaan = 0
    sudah_peringatan = False
    while time.time() - mulai < batas_menit * 60:
        percobaan += 1
        log(f"Attempt #{percobaan} ...")
        try:
            os.startfile(url)
        except OSError:
            sys.exit("Could not open Zoom. Make sure the Zoom desktop app is installed.")

        batas_tunggu = time.time() + tunggu
        batas_keras = time.time() + tunggu * 4   # preview/konek tak boleh menggantung selamanya
        klik_ke, klik_berikut = 0, 0.0
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
                    log("Auto-click failed, please click Join yourself (see the log above).")
                    sudah_peringatan = True
            if status in ("preview", "konek"):  # tunggu proses join selesai
                batas_tunggu = min(batas_keras, max(batas_tunggu, time.time() + 3))
            if status == "masuk":
                log("JOINED THE MEETING!")
                alarm(hwnd, "You joined the Zoom meeting.")
                return True
            if status == "tunggu":
                log("In the waiting room (you got a slot, waiting for the host).")
                alarm(hwnd, "You are in the Zoom waiting room. Don't close it.")
                return True
            time.sleep(0.2)

        log(f"Not in yet (probably full). Trying again in {jeda} seconds.")
        tutup_dialog_zoom()
        time.sleep(jeda)

    log(f"Time limit of {batas_menit} minutes reached, stopping.")
    return False


def masih_di_meeting():
    # Jendela meeting dicek termasuk yang tersembunyi, supaya Zoom yang
    # di-minimize tidak dikira sudah keluar.
    if any(k in SUKSES_KELAS for _, _, k in jendela_zoom(semua=True)):
        return True
    return cek_status()[0] in ("masuk", "tunggu")


def jaga(toleransi=3, interval=2):
    """Pantau meeting; kembali (untuk war ulang) jika terlempar keluar."""
    log("Guard mode on: watching the meeting. Press Ctrl+C to stop.")
    hilang = 0
    while True:
        hilang = 0 if masih_di_meeting() else hilang + 1
        if hilang >= toleransi:            # ~6 detik berturut-turut di luar meeting
            log("Dropped out of the meeting. Joining again...")
            return
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

    if a.kalibrasi:
        kalibrasi()
        return

    link = a.link
    while True:
        link = link or input("Link: ")
        try:
            host, confno, extra = parse_link(link)
            break
        except ValueError:
            print("Invalid link, try again.")
            link = ""
    nama = a.nama
    if not nama:
        print("Your name in Zoom:\n  1. Use your Zoom account's default name\n  2. Type a new name")
        while (pilih := input("Choose (1/2): ").strip()) not in ("1", "2"):
            print("Type 1 or 2.")
        while pilih == "2" and not nama:
            nama = input("Name: ").strip()
    if len(nama) > 64:
        print(f"Warning: the name has {len(nama)} characters, more than 64; Zoom may cut it.")
    url = build_zoommtg(host, confno, extra, nama)
    log(f"Meeting ID {confno} | passcode {'yes' if 'pwd' in extra else 'no'}"
        f"{' | webinar token yes' if 'tk' in extra else ''} | host {host}")
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
        input("Press Enter to close...")
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    if len(sys.argv) == 1:                 # dibuka dengan double-click: jangan langsung tutup.
        atexit.register(_tahan_jendela)    # atexit jalan SETELAH pesan error/traceback tercetak
    if sys.platform == "win32":
        set_console_icon()
    try:
        main()
    except (KeyboardInterrupt, EOFError):  # EOF: input ditutup (Ctrl+Z / pipe kosong)
        log("Stopped.")
