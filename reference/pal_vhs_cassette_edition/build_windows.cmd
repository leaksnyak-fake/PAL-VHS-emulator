setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r pal_vhs\requirements.txt pyinstaller

if not exist ".venv\Scripts\python.exe" (
    echo Create the environment first: py -3.12 -m venv .venv
    exit /b 1
)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --console --name PAL-VHS launcher.py
if errorlevel 1 exit /b 1
echo.
echo Run dist\PAL-VHS\PAL-VHS.exe
echo Keep the entire dist\PAL-VHS folder together, including _internal.
echo FFmpeg and FFprobe must be on PATH for export.
