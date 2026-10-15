# Builds <DistPath>\LocalScribe\LocalScribe.exe (one folder, ~5 GB because of PyTorch + CUDA).
# Usage (from the project folder):  powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-DistPath dist]
# Use another -DistPath while a copy from dist\ is running (Windows locks its files).
# Exit codes are checked explicitly: Windows PowerShell treats any stderr text as an error.
param([string]$DistPath = "dist")
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

& $py -m PyInstaller packaging\localscribe.spec --noconfirm --clean --distpath $DistPath --workpath build
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed"; exit 1 }

# License texts next to the exe as well, where people look for them.
Copy-Item LICENSE, THIRD_PARTY_NOTICES.md "$DistPath\LocalScribe" -Force

$size = (Get-ChildItem "$DistPath\LocalScribe" -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
Write-Host ("Built $DistPath\LocalScribe ({0:N1} GB)" -f $size)
