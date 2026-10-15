@echo off
rem One-time setup for running LocalScribe from source. Downloads about 3 GB.
setlocal
cd /d "%~dp0"

set "UV=uv"
where uv >nul 2>nul
if errorlevel 1 (
    if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe" (
        set "UV=%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe"
    ) else (
        echo uv is not installed. Install it with:
        echo     winget install --id astral-sh.uv -e
        echo then run setup.bat again.
        exit /b 1
    )
)

"%UV%" venv --python 3.11 .venv || exit /b 1
"%UV%" pip install --python .venv\Scripts\python.exe "torch==2.14.1" torchaudio --index-url https://download.pytorch.org/whl/cu126 || exit /b 1
echo torch==2.14.1> "%TEMP%\localscribe-constraints.txt"
"%UV%" pip install --python .venv\Scripts\python.exe --constraint "%TEMP%\localscribe-constraints.txt" -r requirements.txt || exit /b 1

echo.
echo Setup finished. Start the app with run.bat
