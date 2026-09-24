# The full setup on a clean Windows 11 (golden-fl) with the CrossPad on USB:
# install CrossPad the way the guide says, with every extra (PC simulator,
# Arduino version), check the commands in a new terminal, run fl-check.ps1
# (DAW Control on the board, the CrossPad script in FL, both directions), and
# leave FL Studio and the simulator open to look at.
$ErrorActionPreference = "Continue"
$S = "\\host.lan\Data"
$env:GH_TOKEN = (Get-Content "$S\token.txt" -Raw).Trim()
$env:CROSSPAD_YES = "1"; $env:CROSSPAD_NO_TUI = "1"
$env:CROSSPAD_WITH_PC = "1"; $env:CROSSPAD_WITH_ARDUINO = "1"
"started $(Get-Date -Format o)" | Out-File "$S\fl-test.log"
powershell -NoProfile -ExecutionPolicy Bypass -Command 'irm https://raw.githubusercontent.com/CrossPad/crosspad-apps/main/install/install.ps1 | iex' *> "$S\fl-install-crosspad.log"
$env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
& { foreach ($t in "cptools", "crosspad-flash", "crosspad-files", "crosspad-board", "crosspad-idf", "crosspad-hil",
                  "crosspad-bench", "crosspad-sim", "crosspad-pc", "crosspad-arduino", "pio", "code", "node") {
        $c = Get-Command $t -ErrorAction SilentlyContinue
        "{0,-17} {1}" -f $t, ($(if ($c) { $c.Source } else { "MISSING" })) }
} *> "$S\fl-commands.log"
powershell -NoProfile -ExecutionPolicy Bypass -File "$S\fl-check.ps1" -Log "$S\fl-test.log"

# Left open for a person: FL Studio talking to the board, and the simulator.
cmd /c "crosspad-hil cdc APP_START DawControl" | Out-Null
$fl = Get-ChildItem "C:\Program Files\Image-Line" -Recurse -Filter FL64.exe | Select-Object -First 1
if ($fl) { Start-Process $fl.FullName }
Start-Process cmd -ArgumentList "/c", "crosspad-sim" -WindowStyle Minimized

Remove-Item "$S\token.txt" -Force
"done $(Get-Date -Format o)" | Out-File "$S\finished"
