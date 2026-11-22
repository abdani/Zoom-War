<p align="center">
  <img src="docs/images/icon.png" alt="Zoom War icon" width="112">
</p>

<h1 align="center">Zoom War</h1>

<p align="center">
  Ever been stuck outside a full Zoom meeting, fighting everyone else for a seat? Same here, LOL.<br>
  So I built this for all of us: paste the invite link, walk away, and Zoom War keeps trying until a slot opens —<br>
  then sounds the alarm the moment you're in. Like a ticket war, but for Zoom.
</p>

<p align="center">
  <img alt="Windows 10/11" src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?style=for-the-badge&logo=windows11&logoColor=white">
  <img alt="Python 3" src="https://img.shields.io/badge/Python-3.8%2B-3776AB?style=for-the-badge&logo=python&logoColor=white">
  <img alt="Zoom desktop app" src="https://img.shields.io/badge/Zoom-desktop%20app-0B5CFF?style=for-the-badge&logo=zoom&logoColor=white">
  <img alt="MIT License" src="https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge">
</p>

<p align="center">
  <a href="https://abdani.github.io/Zoom-War/"><b>🌐 Homepage</b></a> ·
  <a href="../../archive/refs/heads/main.zip"><b>⬇ Download ZIP</b></a> ·
  double-click <code>zoom_war.bat</code> · Windows 10 / 11
</p>

![Zoom War in its console window: the meeting panel, a full first attempt, in on the second, then guard mode watching the meeting](docs/images/console.png?v=3)

## Features

| Feature | Details |
| --- | --- |
| **Join until you're in** | Opens the meeting in the Zoom desktop app, checks the result, closes the "meeting is full" dialog and tries again every few seconds (5 s minimum). |
| **Any invite link** | `zoom.us/j/…`, vanity hosts like `us06web.zoom.us`, web-client links, webinar links with a registration token (`tk`), or just the meeting ID (`812 3456 7890`). The passcode in the link is used automatically. |
| **Clicks through the preview** | On the "Join with video / audio" screen it turns your microphone and camera **off**, then presses **Join** for you. |
| **Knows where you are** | Tells apart *meeting full*, *connecting*, *preview*, *waiting room* and *in the meeting* by Zoom's own windows. The waiting room counts as a win: you have a slot. |
| **Alarm** | Beeps, brings Zoom to the front and shows a pop-up as soon as you are in. |
| **Guard mode** | After you are in, it keeps watching. If you get dropped, it starts trying again on its own. On by default. |
| **Stays awake** | Keeps the PC from sleeping or turning the screen off while it runs, and lets go when it stops. |
| **Your name** | Join with your Zoom account's name or type another one. |
| **Live console** | A color banner, a meeting panel, color-coded log lines, a spinner while Zoom connects, a countdown bar between attempts and the attempt number in the window title. Falls back to plain text when the output isn't a console. |
| **Calibration mode** | `--calibrate` lists Zoom's windows as they appear, so the markers can be tuned if a Zoom update renames them. |

## Usage

You need Windows 10 or 11, the [Zoom desktop app](https://zoom.us/download) and [Python 3](https://www.python.org/downloads/) (tick **Add to PATH** when installing).

1. Download this repository (**Code → Download ZIP**) and unzip it.
2. Double-click **`zoom_war.bat`**. The first time, it installs [pywinauto](https://github.com/pywinauto/pywinauto) for the automatic clicks.
3. Paste the Zoom invite link, choose your name, and leave the window open.

From a terminal, with options:

```powershell
python zoom_war.py "https://zoom.us/j/81234567890?pwd=xxxx" --name "Your Name"
python zoom_war.py --help
```

| Option | Default | Meaning |
| --- | --- | --- |
| `link` | asked | Zoom invite link or meeting ID |
| `--name NAME` | asked | Display name in the meeting |
| `--delay SECONDS` | 5 | Seconds between attempts (minimum 5) |
| `--wait SECONDS` | 15 | Seconds to wait for the result of each attempt |
| `--limit MINUTES` | 120 | Stop after this many minutes |
| `--no-guard` | off | Stop once you are in instead of watching for a drop |
| `--calibrate` | | Show Zoom's windows as they appear, then exit with <kbd>Ctrl</kbd>+<kbd>C</kbd> |

Press <kbd>Ctrl</kbd>+<kbd>C</kbd> to stop at any time.

> **Window icon.** Windows Terminal ignores an app's icon, so when `zoom_war.bat` opens there it reopens itself in the classic console. That way the Zoom War icon shows in the title bar and on the taskbar.

## How it works

1. The invite link is turned into a `zoommtg://` link (meeting ID, passcode, webinar token, name), which the Zoom desktop app opens directly.
2. Every 0.2 s the script reads the windows that belong to `Zoom.exe` (title and window class) to see what happened: full, connecting, preview, waiting room or in.
3. On the preview screen, [pywinauto](https://github.com/pywinauto/pywinauto) (UI Automation) finds the microphone, camera and **Join** buttons by name and presses them.
4. If the meeting is full, the dialog is closed and the next attempt starts after the delay.

## Development

```powershell
python test_zoom_war.py      # link parser: IDs, passcodes, webinar tokens, invalid links
python tools/capture.py      # icon check: opens zoom_war.bat like a double-click, checks the window
                             # icon, types a made-up link and saves capture.png at the name menu
```

## Built with

| Component | Purpose | License |
| --- | --- | --- |
| [Python](https://www.python.org) (standard library, `ctypes`) | The script, link parsing, reading Zoom's windows | PSF-2.0 |
| [pywinauto](https://github.com/pywinauto/pywinauto) | Pressing the mic, camera and Join buttons on Zoom's preview screen | BSD-3-Clause |
| Win32 `EnumWindows`, `SetThreadExecutionState`, `WM_SETICON` | Detecting Zoom's state, keeping the PC awake, the console window icon | Windows API |
| [Zoom desktop app](https://zoom.us/download) *(installed by you)* | Joins the meeting through its `zoommtg://` link | Zoom's terms |

## Fair use

Use Zoom War only for meetings you are invited to. It waits at least 5 seconds between attempts so it doesn't hammer Zoom. Zoom War is an independent project and is not affiliated with Zoom Communications.

## License

[MIT](LICENSE) © 2026 Dani Abdani
