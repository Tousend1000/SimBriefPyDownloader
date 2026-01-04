# SimBriefPyDownloader

SimBriefPyDownloader is a cross-platform tool to download and manage SimBrief flight plans with a user-friendly interface.

## Features

- Download SimBrief flight plans in multiple formats (PDF, FMS, XPE, FF757, STSFF, TDS, Zibo, XML, MD11)
- Per-format target directories with X-Plane standard folder support
- Flight info display with auto-update polling option
- Automatic file versioning
- System notifications for new plans (optional)
- GPL v3 licensed

## Requirements

Ensure you have Python 3, Tkinter, plyer, requests, and the runtime dependencies installed.

```bash
python3 -m pip install tkinter requests plyer
```

## Build Binaries (PyInstaller)

Install PyInstaller:

```bash
python3 -m pip install pyinstaller
```

Linux (one-file, windowed):

```bash
pyinstaller --onefile --windowed SimBriefPyDownloader.py
```

Windows (one-file, windowed):

```powershell
pyinstaller --onefile --windowed SimBriefPyDownloader.py
```

macOS (one-file, windowed):

```bash
pyinstaller --onefile --windowed SimBriefPyDownloader.py
```

Notes:

- Output binaries are created in `dist/`.
- Add `--icon` if you want platform-specific icons (`.ico` on Windows, `.icns` on macOS).

## Release Notes

### 1.0.3a

- Added `simbrief.ico` and updated PyInstaller spec for desktop builds.

### 1.0.3

- Added auto-update polling with status indicator and system notifications.
- Added X-Plane root support and standard folder presets per format.
- Added per-format tooltips and configurable cleanup age.
- Renamed FF767 format to STSFF and adjusted filename handling for FMS/XPE.
- Moved config storage next to the script.
- Removed underscores after airport indicators in saved files.

## License

[GPL v3](https://www.gnu.org/licenses/gpl-3.0.html)

---

Enjoy your flights! ✈️
