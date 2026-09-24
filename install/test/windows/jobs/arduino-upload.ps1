# After run-fl.ps1 (the Arduino version is set up): the README's line that
# puts the Arduino firmware on the board, then [1] Update my CrossPad to put
# the regular one back, then a smoke test. Output: arduino-upload.log.
$ErrorActionPreference = "Continue"
$S = "\\host.lan\Data"
$env:GH_TOKEN = (Get-Content "$S\token.txt" -Raw).Trim()   # update-board pulls the private project
$env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
& {
    "started $(Get-Date -Format o)"
    "== ports"; Get-CimInstance Win32_SerialPort | ForEach-Object { "$($_.DeviceID)  $($_.Name)  $($_.PNPDeviceID)" }
    "== board before"; cmd /c "crosspad-hil devices"
    "== pio run -e crosspad_v2 -t upload"
    Set-Location C:\CrossPad-Arduino
    cmd /c "pio run -e crosspad_v2 -t upload" 2>&1 | Select-Object -Last 40
    "upload exit=$LASTEXITCODE $(Get-Date -Format o)"
    Start-Sleep 20
    "== board after upload"; cmd /c "crosspad-hil devices"
    "== cptools update-board (the regular firmware back)"
    cmd /c "cptools update-board" 2>&1 | Select-Object -Last 15
    "update-board exit=$LASTEXITCODE $(Get-Date -Format o)"
    "== smoke"; cmd /c "crosspad-hil run smoke" 2>&1 | Select-Object -Last 8
    "smoke exit=$LASTEXITCODE"
    "done $(Get-Date -Format o)"
} *> "$S\arduino-upload.log"
Remove-Item "$S\token.txt" -Force
