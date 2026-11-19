# Builds dist\MiniFloatingCalendar.exe: a single file that runs without Python installed.
# Usage (from this folder):  powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller

# Draw the app icon (.ico) from the same code the tray icon uses.
python -c "import runpy; g = runpy.run_path('mini_floating_calendar.pyw', run_name='build'); g['make_icon_image'](256).save('icon.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"

python -m PyInstaller --noconfirm --clean --onefile --noconsole `
    --name MiniFloatingCalendar --icon icon.ico `
    --hidden-import pystray._win32 `
    mini_floating_calendar.pyw

Write-Host "`nBuilt: $(Resolve-Path dist\MiniFloatingCalendar.exe)"
