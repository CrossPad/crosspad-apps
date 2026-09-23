# SPDX-License-Identifier: MIT
#
# CrossPad setup for Windows — one command, then CP Tools opens.
#
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/CrossPad/crosspad-apps/main/install/install.ps1 | iex"
#
# Safe to run again at any time: every step checks what is already there and
# only installs or repairs what is missing or broken. No administrator rights
# needed: everything goes into your user account and C:\esp, C:\CrossPad.
#
# Options (environment variables):
#   CROSSPAD_DIR=C:\CrossPad       where the project goes (short, no spaces)
#   CROSSPAD_BRANCH=crosspad_v20   which branch of CrossPad/platform-idf
#   CROSSPAD_IDF_DIR=C:\esp\esp-idf
#   CROSSPAD_YES=1                 answer yes to every question
#   CROSSPAD_NO_HIL=1 / CROSSPAD_NO_MCP=1 / CROSSPAD_NO_TUI=1

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"      # Invoke-WebRequest is 10x slower with the bar

function Env-Or($name, $default) { $v = [Environment]::GetEnvironmentVariable($name); if ($v) { $v } else { $default } }
$CrossPadDir = Env-Or "CROSSPAD_DIR" "C:\CrossPad"
$Branch      = Env-Or "CROSSPAD_BRANCH" "crosspad_v20"
$IdfDir      = Env-Or "CROSSPAD_IDF_DIR" "C:\esp\esp-idf"
$IdfTools    = "C:\esp\.espressif"           # short, ASCII-only: user names break ESP-IDF tools
$IdfVersion  = "v5.5.5"
$Repo        = "CrossPad/platform-idf"
$Steps = 8; $script:StepNo = 0; $script:Failed = @()

function Step($title, $what) { $script:StepNo++; Write-Host ""; Write-Host "Step $($script:StepNo) of ${Steps}: $title" -ForegroundColor White; if ($what) { Write-Host "  $what" -ForegroundColor DarkGray } }
function Ok($t)  { Write-Host "  [OK] $t" -ForegroundColor Green }
function Bad($t, $fix) { Write-Host "  [X]  $t" -ForegroundColor Red; if ($fix) { Write-Host "       -> $fix" }; $script:Failed += $t }
function Note($t) { Write-Host "  $t" -ForegroundColor DarkGray }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Ask($q) { if ($env:CROSSPAD_YES) { return $true }; $r = Read-Host "  $q [Y/n]"; return -not ($r -match '^(n|no)$') }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
}
function Add-UserPath($dir) {
    $p = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not ($p -split ";" | Where-Object { $_ -eq $dir })) {
        [Environment]::SetEnvironmentVariable("Path", ($p.TrimEnd(";") + ";" + $dir).TrimStart(";"), "User")
    }
    Refresh-Path
}
function Winget-Install($id) {
    if (-not (Have winget)) { return $false }
    winget install --id $id --exact --silent --scope user --accept-package-agreements --accept-source-agreements *> $null
    if ($LASTEXITCODE -ne 0) {
        winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements *> $null
    }
    Refresh-Path
    return $true
}
function Latest-Asset($repo, $pattern) {
    $rel = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers @{ "User-Agent" = "crosspad" }
    ($rel.assets | Where-Object { $_.name -match $pattern } | Select-Object -First 1).browser_download_url
}
function Download($url, $dest) { Invoke-WebRequest -UseBasicParsing $url -OutFile $dest }

Write-Host "CrossPad setup" -ForegroundColor White
Write-Host "This installs what the CrossPad tools need and opens CP Tools."
Write-Host "It takes 15-30 minutes the first time (mostly downloading), a minute after that."
Write-Host "Project folder: $CrossPadDir"
if (($CrossPadDir + $IdfDir) -match ' ') { Bad "The folders must not contain spaces (ESP-IDF cannot build there)" "set CROSSPAD_DIR to a path without spaces"; exit 1 }
$tmp = Join-Path $env:TEMP "crosspad-setup"; New-Item -ItemType Directory -Force $tmp | Out-Null

# ---------------------------------------------------------------------------
Step "Basic tools" "git and Python 3"
Refresh-Path
if (-not (Have git)) {
    Note "Installing Git for Windows..."
    if (-not (Winget-Install "Git.Git") -or -not (Have git)) {
        $url = Latest-Asset "git-for-windows/git" "^Git-.*-64-bit\.exe$"
        Download $url "$tmp\git.exe"
        Start-Process "$tmp\git.exe" -Wait -ArgumentList "/VERYSILENT", "/NORESTART", "/CURRENTUSER", "/NOCANCEL", "/SP-"
        Refresh-Path
        if (-not (Have git)) { Add-UserPath "$env:LOCALAPPDATA\Programs\Git\cmd" }
    }
}
if (Have git) { Ok "git $((git --version) -replace 'git version ','')" } else { Bad "git did not install" "install it from https://git-scm.com and run this again"; exit 1 }
git config --global core.longpaths true      # ESP-IDF's tree is deep; this is git's half of long paths

function Python-Ok { try { $v = & python -c "import sys; print(sys.version_info >= (3, 10))" 2>$null; return $v -eq "True" } catch { return $false } }
if (-not (Python-Ok)) {
    Note "Installing Python..."
    if (-not (Winget-Install "Python.Python.3.12") -or -not (Python-Ok)) {
        Download "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe" "$tmp\python.exe"
        Start-Process "$tmp\python.exe" -Wait -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0"
        Refresh-Path
    }
}
if (Python-Ok) { Ok "Python $(& python -c 'import platform; print(platform.python_version())')" } else { Bad "Python 3.10 or newer is missing" "install it from https://python.org (tick 'Add to PATH') and run this again"; exit 1 }

# ---------------------------------------------------------------------------
Step "GitHub" "the CrossPad project is shared through GitHub"
if (-not (Have gh)) {
    if (-not (Winget-Install "GitHub.cli") -or -not (Have gh)) {
        $url = Latest-Asset "cli/cli" "windows_amd64\.zip$"
        Download $url "$tmp\gh.zip"
        Expand-Archive -Force "$tmp\gh.zip" "$env:LOCALAPPDATA\gh-cli"
        Add-UserPath "$env:LOCALAPPDATA\gh-cli\bin"
    }
}
if (Have gh) { Ok "GitHub CLI" } else { Bad "GitHub CLI (gh) is missing" "https://cli.github.com" }

# The project repository is private until the CrossPad OS is open.
# Probe it with every credential helper and prompt off: a plain `git
# ls-remote` opens Git Credential Manager's own sign-in window, and the
# user would sign in twice (there, then in gh).
function Can-See-Repo {
    $env:GIT_TERMINAL_PROMPT = "0"; $env:GCM_INTERACTIVE = "never"
    git -c credential.helper= -c "credential.https://github.com.helper=!gh auth git-credential" ls-remote "https://github.com/$Repo" HEAD *> $null
    $ok = $LASTEXITCODE -eq 0
    Remove-Item Env:GIT_TERMINAL_PROMPT, Env:GCM_INTERACTIVE -ErrorAction SilentlyContinue
    return $ok
}
$reach = Can-See-Repo
if (-not $reach -and (Have gh)) {
    gh auth status *> $null
    if ($LASTEXITCODE -ne 0) {
        Note "Sign in to GitHub: a code appears below, your browser opens, paste the code there."
        gh auth login --hostname github.com --git-protocol https --web
    }
    gh auth setup-git *> $null
    $reach = Can-See-Repo
}
if ($reach) { Ok "CrossPad project is reachable" }
else { Bad "Your GitHub account can't see $Repo yet" "ask for access on the CrossPad Discord with your GitHub user name, then run this again"; exit 1 }

# ---------------------------------------------------------------------------
Step "The CrossPad project" $CrossPadDir
if ((Test-Path $CrossPadDir) -and -not (Test-Path "$CrossPadDir\.git")) {
    $aside = "$CrossPadDir.broken-$(Get-Date -Format yyyyMMdd-HHmmss)"
    Note "$CrossPadDir exists but is not a working project - moving it to $aside"
    Move-Item $CrossPadDir $aside
}
if (-not (Test-Path $CrossPadDir)) {
    git clone --branch $Branch "https://github.com/$Repo" $CrossPadDir
    if ($LASTEXITCODE -ne 0) { Bad "Download failed" "check the connection and run this again"; exit 1 }
} else {
    # Only edits to tracked files are "yours": the launcher and .venv this
    # script writes into the folder are untracked and must not block updates.
    $changes = git -C $CrossPadDir status --porcelain --ignore-submodules --untracked-files=no
    if (-not $changes) { git -C $CrossPadDir pull --ff-only --quiet } else { Note "the project has changes of yours - not updating it, only filling in what is missing" }
}
git -C $CrossPadDir submodule update --init --recursive
if ($LASTEXITCODE -eq 0) { Ok "project and its components" } else { Bad "some components did not download" "run this again" }

# ---------------------------------------------------------------------------
Step "ESP-IDF $IdfVersion" "the compiler for the CrossPad's chip - about 15 minutes the first time"
[Environment]::SetEnvironmentVariable("IDF_TOOLS_PATH", $IdfTools, "User"); $env:IDF_TOOLS_PATH = $IdfTools
function Idf-Ok { cmd /c "call `"$IdfDir\export.bat`" >nul 2>&1 && idf.py --version >nul 2>&1"; return $LASTEXITCODE -eq 0 }
if ((Test-Path $IdfDir) -and -not (Test-Path "$IdfDir\.git")) {
    $aside = "$IdfDir.broken-$(Get-Date -Format yyyyMMdd-HHmmss)"
    Note "$IdfDir is not a working ESP-IDF - moving it to $aside"
    Move-Item $IdfDir $aside
}
if (-not (Test-Path $IdfDir)) {
    New-Item -ItemType Directory -Force (Split-Path $IdfDir) | Out-Null
    git -c advice.detachedHead=false clone --quiet --depth 1 --branch $IdfVersion --recursive --shallow-submodules https://github.com/espressif/esp-idf $IdfDir
    if ($LASTEXITCODE -ne 0) { Bad "ESP-IDF download failed" "check the connection and run this again"; exit 1 }
}
$haveVer = git -C $IdfDir describe --tags 2>$null
if ($haveVer -notlike "v5.5*") {
    Note "found ESP-IDF $haveVer; CrossPad needs 5.5 - using $IdfVersion"
    git -C $IdfDir fetch --quiet --depth 1 origin tag $IdfVersion
    git -C $IdfDir checkout --quiet $IdfVersion
    git -C $IdfDir submodule update --quiet --init --recursive --depth 1
}
$idfLog = "$tmp\idf-install.log"
if (-not (Idf-Ok)) {
    # Deleted or edited files inside ESP-IDF come back from its own git first.
    git -C $IdfDir checkout --quiet -- . 2>$null
    git -C $IdfDir submodule update --quiet --init --recursive --depth 1 2>$null
    cmd /c "`"$IdfDir\install.bat`" esp32s3" *> $idfLog
    if (-not (Idf-Ok)) {
        # A broken Python environment is the usual culprit; build it again.
        Remove-Item -Recurse -Force "$IdfTools\python_env\idf5.5_*" -ErrorAction SilentlyContinue
        cmd /c "`"$IdfDir\install.bat`" esp32s3" *>> $idfLog
    }
}
if (Idf-Ok) { Ok "ESP-IDF $(git -C $IdfDir describe --tags)" } else { Bad "ESP-IDF did not install" "the details are in $idfLog - send it on Discord (#support)" }

# ---------------------------------------------------------------------------
Step "USB access" "Windows has the drivers built in"
Ok "nothing to do"
$lp = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -ErrorAction SilentlyContinue).LongPathsEnabled
if ($lp -ne 1) { Note "Windows long paths are off; the short folders above keep builds under the limit." }

# ---------------------------------------------------------------------------
Step "Test tools (optional)" "crosspad-hil: lets CP Tools and AI agents check the board automatically"
if ($env:CROSSPAD_NO_HIL) { Note "skipped" } else {
    $venv = "$CrossPadDir\.venv"
    if ((Test-Path "$venv\Scripts\crosspad-hil.exe")) { Ok "crosspad-hil" } else {
        Remove-Item -Recurse -Force $venv -ErrorAction SilentlyContinue
        & python -m venv $venv
        & "$venv\Scripts\pip.exe" install -q "git+https://github.com/CrossPad/crosspad-hil" *> "$tmp\hil-install.log"
        if ($LASTEXITCODE -eq 0) { Ok "crosspad-hil" } else { Note "crosspad-hil could not be installed (it needs access to CrossPad/crosspad-hil) - CP Tools works without it" }
    }
}

# ---------------------------------------------------------------------------
Step "AI assistant tools (optional)" "the CrossPad MCP server, for Claude Code"
if ($env:CROSSPAD_NO_MCP) { Note "skipped" }
elseif ((Have claude) -and (Have npx)) {
    claude mcp get crosspad *> $null
    if ($LASTEXITCODE -eq 0) { Ok "Claude Code already knows the CrossPad tools" }
    else { claude mcp add --scope user crosspad -- npx -y crosspad-mcp-server *> $null; if ($LASTEXITCODE -eq 0) { Ok "added to Claude Code" } else { Note "run: claude mcp add crosspad -- npx -y crosspad-mcp-server" } }
} else { Note "Claude Code or Node.js is not installed - nothing to set up (add later: claude mcp add crosspad -- npx -y crosspad-mcp-server)" }

# ---------------------------------------------------------------------------
Step "CP Tools" "a launcher on the desktop, then a check of everything"
$launcher = "$CrossPadDir\cptools.cmd"
@"
@echo off
rem CP Tools launcher, written by the CrossPad installer. Run: cptools [doctor^|support^|tui]
cd /d "$CrossPadDir"
set IDF_TOOLS_PATH=$IdfTools
call "$IdfDir\export.bat" >nul 2>&1
if "%~1"=="" (python tools\app_manager.py tui) else (python tools\app_manager.py %*)
"@ | Set-Content -Encoding ASCII $launcher
# Python edits the personal config: it keeps every other key (Windows
# PowerShell 5.1 cannot round-trip JSON into a hashtable).
& python -c "import json,sys,pathlib; p=pathlib.Path(sys.argv[1]); c=json.loads(p.read_text()) if p.exists() else {}; c['idf_path']=sys.argv[2]; p.write_text(json.dumps(c, indent=2)+chr(10))" "$CrossPadDir\crosspad.local.json" $IdfDir
try {
    $sh = (New-Object -ComObject WScript.Shell).CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\CP Tools.lnk")
    $sh.TargetPath = $launcher; $sh.WorkingDirectory = $CrossPadDir; $sh.Save()
    Ok "desktop shortcut 'CP Tools'"
} catch { Note "no desktop shortcut - open $launcher instead" }
# The doctor's view of the whole setup. A board that is not plugged in yet is
# not an installation problem, so only this script's own steps decide below.
cmd /c "`"$launcher`" doctor"

Write-Host ""
if ($script:Failed.Count -eq 0) {
    Write-Host "All set. Next time, open 'CP Tools' on the desktop." -ForegroundColor Green
    Write-Host "Plug your CrossPad in with a USB cable before [1] Update my CrossPad."
} else {
    Write-Host "Almost: the lines marked [X] above say what is left." -ForegroundColor Yellow
    Write-Host "Run this installer again after fixing them - it only redoes what is missing."
}
if (-not $env:CROSSPAD_NO_TUI) { Write-Host "Opening CP Tools..."; cmd /c "`"$launcher`"" }
