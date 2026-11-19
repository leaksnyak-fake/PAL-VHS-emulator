@echo off
setlocal
set "app=%~dp0app"
if not exist "%app%\PAL-VHS.exe" (
    echo PAL-VHS.exe is missing. Extract the complete release ZIP and keep the app folder beside this launcher.
    if "%~1"=="" pause
    exit /b 1
)
set "PATH=%app%;%PATH%"
if exist "%app%\lib\gstreamer-1.0\" set "PAL_VHS_GSTREAMER_ROOT=%app%"
if "%~1"=="" (
    start "" "%app%\PAL-VHS.exe"
    exit /b
)
"%app%\PAL-VHS.exe" %*
exit /b %ERRORLEVEL%
