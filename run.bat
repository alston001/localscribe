@echo off
rem Starts LocalScribe from source (after setup.bat). pythonw = no console window.
cd /d "%~dp0"

if not exist ".venv\pyvenv.cfg" (
    echo .venv is missing. Run setup.bat first.
    pause
    exit /b 1
)

rem The venv's launcher needs the Python it was created from; check it before starting,
rem because a missing one only shows a cryptic "Python Launcher is sorry to say" box.
set "PYHOME="
for /f "usebackq tokens=1,* delims== " %%a in (".venv\pyvenv.cfg") do if /i "%%a"=="home" set "PYHOME=%%b"
if not exist "%PYHOME%\pythonw.exe" (
    echo The Python that .venv was built with is not installed:
    echo     %PYHOME%
    echo.
    echo Install that exact version, then start run.bat again:
    echo     uv python install 3.11.17
    echo or run setup.bat to rebuild .venv.
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" run_localscribe.py %*
