@echo off
rem Starts LocalScribe from source (after setup.bat). pythonw = no console window.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" run_localscribe.py %*
