# Started once by C:\OEM\runner.ps1 (as run-test.ps1) on the VM winrunner.sh
# creates: Git for Windows, then the GitHub Actions runner as a service.
# Output in setup.log, then "finished".
$S = "\\host.lan\Data"
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Start-Transcript "$S\setup.log"
try {
    $cfg = @{}
    Get-Content "$S\runner.cfg" | ForEach-Object { $k, $v = $_ -split "=", 2; $cfg[$k] = $v }
    # Read and delete first: the token never stays on the share.
    $token = (Get-Content "$S\token.txt" -Raw).Trim()
    Remove-Item "$S\token.txt" -Force

    # QEMU hands Windows the host's local time as the RTC; under the golden
    # disk's Pacific zone the clock ran 7 h ahead and GitHub refused the
    # runner's tokens ("The token is not valid until ..."). The host's zone,
    # and the time service on, so a drifted clock comes back by itself.
    Set-TimeZone -Id $cfg.TZ
    Set-Service w32time -StartupType Automatic
    Start-Service w32time
    w32tm /resync /force

    # Restricted out of the box: actions/setup-python runs the setup.ps1 it
    # downloads, which hosted runners allow. It throws when this script's own
    # Bypass overrides it, after it has set it.
    try { Set-ExecutionPolicy RemoteSigned -Scope LocalMachine -Force } catch {}
    if ((Get-ExecutionPolicy -Scope LocalMachine) -ne "RemoteSigned") { throw "execution policy not set" }

    $h = @{ "User-Agent" = "crosspad-winrunner" }
    $gitUrl = (Invoke-RestMethod "https://api.github.com/repos/git-for-windows/git/releases/latest" -Headers $h).assets |
        Where-Object name -Match '^Git-[0-9.]+-64-bit\.exe$' | Select-Object -First 1 -ExpandProperty browser_download_url
    Invoke-WebRequest $gitUrl -OutFile "$env:TEMP\git.exe"
    Start-Process "$env:TEMP\git.exe" -ArgumentList "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES" -Wait
    & "C:\Program Files\Git\cmd\git.exe" config --system core.longpaths true
    # A run: step's default shell is pwsh when there is one, as on hosted
    # runners; Windows PowerShell 5.1 does not know &&.
    $pwshUrl = (Invoke-RestMethod "https://api.github.com/repos/PowerShell/PowerShell/releases/latest" -Headers $h).assets |
        Where-Object name -Match '^PowerShell-[0-9.]+-win-x64\.msi$' | Select-Object -First 1 -ExpandProperty browser_download_url
    Invoke-WebRequest $pwshUrl -OutFile "$env:TEMP\pwsh.msi"
    Start-Process msiexec.exe -ArgumentList "/i", "$env:TEMP\pwsh.msi", "/quiet", "ADD_PATH=1" -Wait

    $dir = "C:\actions-runner"
    New-Item -ItemType Directory -Force $dir | Out-Null
    # The test suite is thousands of small files: Defender scanning each one
    # costs more than the tests.
    Add-MpPreference -ExclusionPath $dir
    $runUrl = (Invoke-RestMethod "https://api.github.com/repos/actions/runner/releases/latest" -Headers $h).assets |
        Where-Object name -Match '^actions-runner-win-x64-[0-9.]+\.zip$' | Select-Object -First 1 -ExpandProperty browser_download_url
    Invoke-WebRequest $runUrl -OutFile "$env:TEMP\runner.zip"
    Expand-Archive "$env:TEMP\runner.zip" $dir -Force

    # SYSTEM, not the default NETWORK SERVICE: actions/setup-python runs the
    # Python installer, which needs an administrator.
    Push-Location $dir
    & .\config.cmd --unattended --url "https://github.com/$($cfg.REPO)" --token $token `
        --name $cfg.NAME --labels $cfg.LABEL --work _work --replace `
        --runasservice --windowslogonaccount "NT AUTHORITY\SYSTEM"
    if ($LASTEXITCODE -ne 0) { throw "config.cmd exit $LASTEXITCODE" }
    Pop-Location
    Get-Service "actions.runner.*" | Format-Table Name, Status, StartType
    "RESULT: OK"
} catch {
    "RESULT: FAIL $_"
} finally {
    Stop-Transcript
    "done $(Get-Date -Format o)" | Out-File "$S\finished"
}
