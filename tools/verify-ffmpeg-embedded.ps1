<#
.SYNOPSIS
    Proves that ffmpeg really ends up INSIDE the one-file .exe.

.DESCRIPTION
    Builds ndxvo_converter.py twice with PyInstaller - once without ffmpeg and
    once with --add-binary - then reports both sizes and reads the PyInstaller
    archive appended to the executable to list its entries.

    Expected result: the "with" build is roughly 30 MB larger, and ffmpeg.exe
    shows up in the archive listing of the "with" build only.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\verify-ffmpeg-embedded.ps1
#>

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== Installing build dependencies ==" -ForegroundColor Cyan
python -m pip install --quiet --upgrade pip
python -m pip install --quiet pillow pyinstaller "imageio-ffmpeg==0.6.0"

Write-Host "== Extracting the static ffmpeg binary ==" -ForegroundColor Cyan
$ff = python -c "import imageio_ffmpeg, sys; sys.stdout.write(imageio_ffmpeg.get_ffmpeg_exe())"
New-Item -ItemType Directory -Force -Path vendor | Out-Null
Copy-Item $ff vendor\ffmpeg.exe -Force
$ffSize = (Get-Item vendor\ffmpeg.exe).Length
Write-Host ("vendor\ffmpeg.exe: {0:N0} bytes ({1:N1} MB)" -f $ffSize, ($ffSize / 1MB))
& .\vendor\ffmpeg.exe -version | Select-Object -First 1

Write-Host "`n== BUILD A: without ffmpeg ==" -ForegroundColor Cyan
pyinstaller --noconfirm --clean --windowed --onefile `
  --name "probe-without-ffmpeg" `
  --hidden-import "PIL._tkinter_finder" `
  ndxvo_converter.py | Out-Null

Write-Host "`n== BUILD B: with ffmpeg ==" -ForegroundColor Cyan
pyinstaller --noconfirm --clean --windowed --onefile `
  --name "probe-with-ffmpeg" `
  --add-binary "vendor/ffmpeg.exe;." `
  --hidden-import "PIL._tkinter_finder" `
  ndxvo_converter.py | Out-Null

$a = (Get-Item "dist\probe-without-ffmpeg.exe").Length
$b = (Get-Item "dist\probe-with-ffmpeg.exe").Length

Write-Host "`n== RESULT ==" -ForegroundColor Cyan
Write-Host ("  without ffmpeg : {0,12:N0} bytes ({1,6:N1} MB)" -f $a, ($a / 1MB))
Write-Host ("  with ffmpeg    : {0,12:N0} bytes ({1,6:N1} MB)" -f $b, ($b / 1MB))
Write-Host ("  difference     : {0,12:N0} bytes ({1,6:N1} MB)" -f ($b - $a), (($b - $a) / 1MB))

Write-Host "`n== Archive contents of the 'with' build ==" -ForegroundColor Cyan
$listing = python -m PyInstaller.utils.cliutils.archive_viewer --list --brief "dist\probe-with-ffmpeg.exe"
if ($listing -match "ffmpeg\.exe") {
    Write-Host "  OK - ffmpeg.exe is embedded in the one-file executable." -ForegroundColor Green
} else {
    Write-Host "  FAIL - ffmpeg.exe was NOT found in the archive." -ForegroundColor Red
    exit 1
}

$listing2 = python -m PyInstaller.utils.cliutils.archive_viewer --list --brief "dist\probe-without-ffmpeg.exe"
if ($listing2 -match "ffmpeg\.exe") {
    Write-Host "  Unexpected - the control build also contains ffmpeg.exe." -ForegroundColor Yellow
} else {
    Write-Host "  OK - the control build does not contain it, as expected." -ForegroundColor Green
}

Write-Host "`nRun dist\probe-with-ffmpeg.exe to confirm the app starts without ffmpeg on PATH."
