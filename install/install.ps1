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
#   CROSSPAD_NO_HIL=1 / CROSSPAD_NO_VSCODE=1 / CROSSPAD_NO_MCP=1 / CROSSPAD_NO_TUI=1

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"      # Invoke-WebRequest is 10x slower with the bar

function Env-Or($name, $default) { $v = [Environment]::GetEnvironmentVariable($name); if ($v) { $v } else { $default } }
$CrossPadDir = Env-Or "CROSSPAD_DIR" "C:\CrossPad"
$Branch      = Env-Or "CROSSPAD_BRANCH" "crosspad_v20"
$IdfDir      = Env-Or "CROSSPAD_IDF_DIR" "C:\esp\esp-idf"
$IdfTools    = "C:\esp\.espressif"           # short, ASCII-only: user names break ESP-IDF tools
$IdfVersion  = "v5.5.5"
$Repo        = "CrossPad/platform-idf"
$Steps = 10; $script:StepNo = 0; $script:Failed = @()

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
# git itself must use the gh sign-in for github.com (clone, submodules, pip).
if (Have gh) { gh auth status *> $null; if ($LASTEXITCODE -eq 0) { gh auth setup-git *> $null } }
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
Step "VS Code" "the editor, with the ESP-IDF extension and the CP Tools buttons"
# This machine's real paths into .vscode\settings.json (kept, merged): the
# template in the repository names Linux paths.
$vsSettingsPy = @'
import json, pathlib, re, sys
proj, idf, tools = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
vs = proj / ".vscode"
envs = sorted((p.name for p in (pathlib.Path(tools) / "python_env").glob("idf*_env")), reverse=True)
py = str(pathlib.Path(tools) / "python_env" / envs[0] / "Scripts" / "python.exe") if envs else "python"
settings = {}
tpl = vs / "settings.template.json"
if tpl.exists():
    settings = json.loads(re.sub(r"@@IDF_PYTHON_ENV@@", envs[0] if envs else "", tpl.read_text(encoding="utf-8")))
out = vs / "settings.json"
if out.exists():
    try:
        settings.update(json.loads(out.read_text(encoding="utf-8")))
    except ValueError:
        pass
settings.update({"idf.espIdfPath": idf, "idf.currentSetup": idf, "idf.toolsPath": tools,
                 "idf.pythonBinPath": py})
vs.mkdir(exist_ok=True)
out.write_text(json.dumps(settings, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
'@
if ($env:CROSSPAD_NO_VSCODE) { Note "skipped" } else {
    if (-not (Have code)) {
        Note "Installing VS Code..."
        if (-not (Winget-Install "Microsoft.VisualStudioCode") -or -not (Have code)) {
            Download "https://update.code.visualstudio.com/latest/win32-x64-user/stable" "$tmp\vscode.exe"
            Start-Process "$tmp\vscode.exe" -Wait -ArgumentList "/VERYSILENT", "/NORESTART", "/MERGETASKS=!runcode,addtopath"
            Refresh-Path
            if (-not (Have code)) { Add-UserPath "$env:LOCALAPPDATA\Programs\Microsoft VS Code\bin" }
        }
    }
    if (Have code) {
        cmd /c "code --install-extension espressif.esp-idf-extension --install-extension ms-vscode.cpptools --install-extension spencerwmiles.vscode-task-buttons --force" *> "$tmp\vscode.log"
        if ($LASTEXITCODE -eq 0) { Ok "VS Code with the ESP-IDF, C/C++ and task-button extensions" }
        else { Bad "VS Code extensions did not install" "details in $tmp\vscode.log" }
        $vsSettingsPy | Set-Content -Encoding UTF8 "$tmp\vscode_settings.py"
        & python "$tmp\vscode_settings.py" $CrossPadDir $IdfDir $IdfTools
        if ($LASTEXITCODE -eq 0) { Ok "VS Code settings point at ESP-IDF ($IdfDir)" }
    } else { Bad "VS Code did not install" "get it from https://code.visualstudio.com and run this again" }
}

# ---------------------------------------------------------------------------
Step "AI assistant tools" "Node.js and the CrossPad MCP server, for VS Code and Claude Code"
$mcpConfigPy = @'
import json, pathlib, sys
proj, idf = pathlib.Path(sys.argv[1]), sys.argv[2]
out = proj / ".vscode" / "mcp.json"
cfg = {}
if out.exists():
    try:
        cfg = json.loads(out.read_text())
    except ValueError:
        pass
cfg.setdefault("servers", {})["crosspad"] = {
    "type": "stdio", "command": "npx", "args": ["-y", "crosspad-mcp-server@latest"],
    "env": {"CROSSPAD_IDF_ROOT": str(proj), "IDF_PATH": idf}}
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(cfg, indent=4) + "\n")
'@
# Start the server the way an editor does and ask for its tools.
$mcpAnswersPy = @'
import json, os, shutil, subprocess, sys, threading
env = dict(os.environ, CROSSPAD_IDF_ROOT=sys.argv[1], IDF_PATH=sys.argv[2])
msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "crosspad-installer", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
# stdin stays open until the answer: a stdio server ends when its client does.
try:
    p = subprocess.Popen([shutil.which("npx") or "npx", "-y", "crosspad-mcp-server@latest"],
                         env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
except OSError:
    sys.exit(1)
p.stdin.write("".join(json.dumps(m) + "\n" for m in msgs))
p.stdin.flush()
found = []
def read():
    for line in p.stdout:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("id") == 2:
            found.append(len(msg.get("result", {}).get("tools", [])))
            return
t = threading.Thread(target=read, daemon=True)
t.start()
t.join(240)
p.kill()
if not found:
    sys.exit(1)
print(found[0])
'@
function Node-Ok { if (-not (Have node)) { return $false }; node -e "process.exit(parseInt(process.versions.node) >= 18 ? 0 : 1)" 2>$null; return $LASTEXITCODE -eq 0 }
if ($env:CROSSPAD_NO_MCP) { Note "skipped" } else {
    if (-not (Node-Ok)) {
        Note "Installing Node.js..."
        if (-not (Winget-Install "OpenJS.NodeJS.LTS") -or -not (Node-Ok)) {
            $idx = Invoke-RestMethod "https://nodejs.org/dist/index.json"
            $ver = ($idx | Where-Object { $_.lts } | Select-Object -First 1).version
            Download "https://nodejs.org/dist/$ver/node-$ver-win-x64.zip" "$tmp\node.zip"
            Expand-Archive -Force "$tmp\node.zip" "$env:LOCALAPPDATA"
            Add-UserPath "$env:LOCALAPPDATA\node-$ver-win-x64"
        }
    }
    if ((Node-Ok) -and (Have npx)) {
        Ok "Node.js $(node --version)"
        $mcpConfigPy | Set-Content -Encoding UTF8 "$tmp\mcp_config.py"
        & python "$tmp\mcp_config.py" $CrossPadDir $IdfDir
        if ($LASTEXITCODE -eq 0) { Ok "VS Code knows the CrossPad MCP server (.vscode\mcp.json)" }
        if (Have claude) {
            claude mcp get crosspad *> $null
            if ($LASTEXITCODE -ne 0) { claude mcp add --scope user crosspad -e "CROSSPAD_IDF_ROOT=$CrossPadDir" -e "IDF_PATH=$IdfDir" -- npx -y crosspad-mcp-server@latest *> $null }
            claude mcp get crosspad *> $null
            if ($LASTEXITCODE -eq 0) { Ok "Claude Code knows it too" }
        }
        $mcpAnswersPy | Set-Content -Encoding UTF8 "$tmp\mcp_answers.py"
        $n = & python "$tmp\mcp_answers.py" $CrossPadDir $IdfDir
        if ($LASTEXITCODE -eq 0) { Ok "the MCP server starts and offers $n tools" }
        else { Bad "the MCP server did not answer" "run: npx -y crosspad-mcp-server@latest - and send what it prints on Discord (#support)" }
    } else { Bad "Node.js 18 or newer is missing" "install it from https://nodejs.org and run this again" }
}

# ---------------------------------------------------------------------------
Step "CP Tools" "a desktop shortcut, cptools and the crosspad-* commands in any terminal"
# One small .cmd per command: each sets up ESP-IDF itself, so nobody has to
# remember export.bat or a path into tools\. They live in the project's bin\,
# which goes on the user PATH.
$bin = "$CrossPadDir\bin"
New-Item -ItemType Directory -Force $bin | Out-Null
function Shim($name, $target) {
@"
@echo off
rem $name - written by the CrossPad installer
set IDF_TOOLS_PATH=$IdfTools
call "$IdfDir\export.bat" >nul 2>&1
$target %*
"@ | Set-Content -Encoding ASCII "$bin\$name.cmd"
}
Shim "crosspad-flash" "python `"$CrossPadDir\tools\ota_flash.py`""
Shim "crosspad-files" "python `"$CrossPadDir\tools\fs_transfer.py`""
Shim "crosspad-bench" "python `"$CrossPadDir\tools\bench.py`""
Shim "crosspad-board" "python `"$CrossPadDir\tools\crosspad_board.py`""
Shim "crosspad-idf" "idf.py -C `"$CrossPadDir`""
if (Test-Path "$CrossPadDir\.venv\Scripts\crosspad-hil.exe") { Shim "crosspad-hil" "`"$CrossPadDir\.venv\Scripts\crosspad-hil.exe`"" }
# cptools with no arguments opens the TUI.
@"
@echo off
rem cptools - written by the CrossPad installer. Run: cptools [doctor^|support^|update-board^|list^|...]
set IDF_TOOLS_PATH=$IdfTools
call "$IdfDir\export.bat" >nul 2>&1
if "%~1"=="" (python "$CrossPadDir\tools\app_manager.py" tui) else (python "$CrossPadDir\tools\app_manager.py" %*)
"@ | Set-Content -Encoding ASCII "$bin\cptools.cmd"
$launcher = "$bin\cptools.cmd"
Copy-Item $launcher "$CrossPadDir\cptools.cmd" -Force     # the path older shortcuts point at
# Python edits the personal config: it keeps every other key (Windows
# PowerShell 5.1 cannot round-trip JSON into a hashtable).
& python -c "import json,sys,pathlib; p=pathlib.Path(sys.argv[1]); c=json.loads(p.read_text()) if p.exists() else {}; c['idf_path']=sys.argv[2]; p.write_text(json.dumps(c, indent=2)+chr(10))" "$CrossPadDir\crosspad.local.json" $IdfDir
Add-UserPath $bin
Ok "$((Get-ChildItem $bin -Name) -replace '\.cmd$','' -join ' ') - from any new terminal"
try {
    $sh = (New-Object -ComObject WScript.Shell).CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\CP Tools.lnk")
    $sh.TargetPath = $launcher; $sh.WorkingDirectory = $CrossPadDir; $sh.Save()
    Ok "desktop shortcut 'CP Tools'"
} catch { Note "no desktop shortcut - open $launcher instead" }

# ---------------------------------------------------------------------------
Step "Final check" "in a new terminal, the way you will use it"
Refresh-Path              # exactly the PATH a new window gets from the registry
foreach ($t in @("git", "python", "gh", "code", "node", "npx") + ((Get-ChildItem $bin -Name) -replace '\.cmd$','')) {
    if ($t -eq "code" -and $env:CROSSPAD_NO_VSCODE) { continue }
    if (($t -eq "node" -or $t -eq "npx") -and $env:CROSSPAD_NO_MCP) { continue }
    $found = powershell -NoProfile -Command "[bool](Get-Command $t -ErrorAction SilentlyContinue)"
    if ($found -eq "True") { Ok "$t is on PATH" } else { Bad "$t is not on PATH in a new terminal" "open a new terminal and run this installer again" }
}
cmd /c "set IDF_TOOLS_PATH=$IdfTools&& call `"$IdfDir\export.bat`" >nul 2>&1 && idf.py --version >nul 2>&1"
if ($LASTEXITCODE -eq 0) { Ok "idf.py works inside cptools" } else { Bad "idf.py does not start" "run this installer again" }
# The doctor's view of the whole setup. A board that is not plugged in yet is
# not an installation problem, so only this script's own steps decide below.
cmd /c "cptools doctor"

Write-Host ""
if ($script:Failed.Count -eq 0) {
    Write-Host "All set. Next time, open 'CP Tools' on the desktop, or type cptools in a terminal." -ForegroundColor Green
    Write-Host "Plug your CrossPad in with a USB cable before [1] Update my CrossPad."
} else {
    Write-Host "Almost: the lines marked [X] above say what is left." -ForegroundColor Yellow
    Write-Host "Run this installer again after fixing them - it only redoes what is missing."
}
if (-not $env:CROSSPAD_NO_TUI) { Write-Host "Opening CP Tools..."; cmd /c "`"$launcher`"" }
