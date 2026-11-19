# Build on Windows

Run these in Command Prompt from the extracted folder containing `pal_vhs` and
`launcher.py`. Python installation and virtual-environment creation are separate:

```cmd
py install 3.12
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r pal_vhs\requirements.txt pyinstaller
build_windows.cmd
dist\PAL-VHS\PAL-VHS.exe
```

If Python 3.12 is already installed, omit the first command. A classic Python
launcher without the `install` command requires installing Python from python.org.

Distribute the **entire `dist\PAL-VHS` directory**, including `_internal`.
Do not launch or distribute the temporary EXE inside `build\PAL-VHS`.
FFmpeg and FFprobe must be installed and on PATH for export:

```cmd
ffmpeg -version
ffprobe -version
```

The supplied launcher calls `multiprocessing.freeze_support()` before importing
the application, so frozen render workers do not recursively launch the GUI.
Frozen builds now use one background render thread by default. See
[renderer recovery](RENDERER_RECOVERY.md) for the BrokenProcessPool fix,
diagnostic log paths, and optional process-backend commands.
The build script keeps a console visible for diagnostics. After testing, replace
`--console` with `--windowed` in the script if desired.

This release was tested as Python source on Linux, including Qt widgets and
FFmpeg exports. A new Windows-frozen executable was not built or tested here.
