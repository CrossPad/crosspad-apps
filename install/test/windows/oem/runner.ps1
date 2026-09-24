# At every logon: say "ready" to the host, wait for a run-test.ps1 in the share,
# claim it (rename, so it runs once) and run it.
$share = "\\host.lan\Data"
while (-not (Test-Path $share)) { Start-Sleep 5 }
"ready $(Get-Date -Format o)" | Out-File "$share\ready.txt"
while (-not (Test-Path "$share\run-test.ps1")) { Start-Sleep 5 }
Move-Item "$share\run-test.ps1" "$share\run-test.started.ps1" -Force
powershell -NoProfile -ExecutionPolicy Bypass -File "$share\run-test.started.ps1"
