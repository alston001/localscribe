# Builds dist\LocalScribe\LocalScribe.exe (one folder, ~5 GB because of PyTorch + CUDA).
# Usage (from the project folder):  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# Exit codes are checked explicitly: Windows PowerShell treats any stderr text as an error.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path $PSScriptRoot)
$py = ".\.venv\Scripts\python.exe"

& $py -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    uv pip install --python $py "pyinstaller==6.22.3"
    if ($LASTEXITCODE -ne 0) { Write-Error "Could not install PyInstaller"; exit 1 }
}

& $py packaging\make_icon.py
if ($LASTEXITCODE -ne 0) { Write-Error "Icon generation failed"; exit 1 }

& $py -m PyInstaller packaging\localscribe.spec --noconfirm --clean --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed"; exit 1 }

$size = (Get-ChildItem dist\LocalScribe -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
Write-Host ("Built dist\LocalScribe ({0:N1} GB)" -f $size)
