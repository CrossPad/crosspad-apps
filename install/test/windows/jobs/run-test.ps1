# Clean Windows 11, final check: the install line exactly as the guide gives it
# (downloaded from GitHub), then broken on purpose and run again.
$ErrorActionPreference = "Continue"
$S = "\\host.lan\Data"
$env:GH_TOKEN = (Get-Content "$S\token.txt" -Raw).Trim()
$env:CROSSPAD_YES = "1"; $env:CROSSPAD_NO_TUI = "1"
"started $(Get-Date -Format o) as $env:USERNAME, PS $($PSVersionTable.PSVersion)" | Out-File "$S\runner.log"
$line = 'irm https://raw.githubusercontent.com/CrossPad/crosspad-apps/main/install/install.ps1 | iex'
function Run($name) {
    "== $name $(Get-Date -Format o)" | Out-File "$S\win-$name.log"
    powershell -NoProfile -ExecutionPolicy Bypass -Command $line *>> "$S\win-$name.log"
    "exit=$LASTEXITCODE $(Get-Date -Format o)" | Out-File -Append "$S\win-$name.log"
    & C:\CrossPad\cptools.cmd doctor *>> "$S\win-$name.log"
    "doctor exit=$LASTEXITCODE" | Out-File -Append "$S\win-$name.log"
}
Run "1-fresh"
Remove-Item -Recurse -Force C:\esp\.espressif\python_env -ErrorAction SilentlyContinue
Remove-Item -Force C:\CrossPad\components\crosspad-sampler\.git -ErrorAction SilentlyContinue
Rename-Item C:\esp\esp-idf\tools tools.gone -ErrorAction SilentlyContinue
Run "2-broken"
Remove-Item "$S\token.txt" -Force
[Environment]::SetEnvironmentVariable("GH_TOKEN", $null, "User")
"done $(Get-Date -Format o)" | Out-File "$S\finished"
