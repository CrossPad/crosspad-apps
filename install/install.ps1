# SPDX-License-Identifier: MIT
#
# CrossPad setup for Windows — one command, then CP Tools opens.
#
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/CrossPad/crosspad-apps/main/install/install.ps1 | iex"
#
# Safe to run again at any time: every step checks what is already there and
# only installs or repairs what is missing or broken. No administrator rights
# needed: everything goes into your user account and C:\esp, C:\CrossPad. The
# one exception is the PC simulator's Visual Studio C++ tools (Windows asks once).
#
# Options (environment variables):
#   CROSSPAD_DIR=C:\CrossPad       where the project goes (short, no spaces)
#   CROSSPAD_BRANCH=crosspad_v20   which branch of CrossPad/platform-idf
#   CROSSPAD_IDF_DIR=C:\esp\esp-idf   (default: an ESP-IDF 5.5 already here, else this)
#   CROSSPAD_YES=1                 answer yes to every question (extras stay off)
#   CROSSPAD_WITH_PC=1             also set up the PC simulator (C:\CrossPad-PC)
#   CROSSPAD_WITH_ARDUINO=1        also set up the Arduino version (C:\CrossPad-Arduino)
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
$PcDir       = Env-Or "CROSSPAD_PC_DIR" "C:\CrossPad-PC"
# The simulator and the Arduino version live on their development branches:
# master/main there predate the app manager and the 2.0 board.
$PcBranch    = Env-Or "CROSSPAD_PC_BRANCH" "feat/virtual-audio-on-pipeline"
$ArduinoDir  = Env-Or "CROSSPAD_ARDUINO_DIR" "C:\CrossPad-Arduino"
$ArduinoBranch = Env-Or "CROSSPAD_ARDUINO_BRANCH" "feat/audio-module-arduino"
$WithPc      = [bool]$env:CROSSPAD_WITH_PC
$WithArduino = [bool]$env:CROSSPAD_WITH_ARDUINO
$Steps = 10; $script:StepNo = 0; $script:Failed = @()

function Step($title, $what) { $script:StepNo++; Write-Host ""; Write-Host "Step $($script:StepNo) of ${Steps}: $title" -ForegroundColor White; if ($what) { Write-Host "  $what" -ForegroundColor DarkGray } }
function Ok($t)  { Write-Host "  [OK] $t" -ForegroundColor Green }
function Bad($t, $fix) { Write-Host "  [X]  $t" -ForegroundColor Red; if ($fix) { Write-Host "       -> $fix" }; $script:Failed += $t }
function Note($t) { Write-Host "  $t" -ForegroundColor DarkGray }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Ask($q) { if ($env:CROSSPAD_YES) { return $true }; $r = Read-Host "  $q [Y/n]"; return -not ($r -match '^(n|no)$') }
function Ask-No($q) { if ($env:CROSSPAD_YES) { return $false }; $r = Read-Host "  $q [y/N]"; return ($r -match '^(y|yes|t|tak)$') }
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
if (-not ($WithPc -or $WithArduino) -and -not $env:CROSSPAD_YES) {
    Write-Host ""
    Write-Host "Optional - answer now, then you can leave it running:"
    $WithPc = Ask-No "Also set up the PC simulator (the CrossPad on this computer's screen)?"
    $WithArduino = Ask-No "Also set up the Arduino (PlatformIO) version of the firmware?"
}
if ($WithPc) { $Steps++ }
if ($WithArduino) { $Steps++ }

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
    if (-not $changes) { git -C $CrossPadDir pull --ff-only --quiet; if ($LASTEXITCODE -ne 0) { Note "left the project as it is (it has its own commits)" } } else { Note "the project has changes of yours - not updating it, only filling in what is missing" }
}
git -C $CrossPadDir submodule update --init --recursive
if ($LASTEXITCODE -eq 0) { Ok "project and its components" } else { Bad "some components did not download" "run this again" }

# ---------------------------------------------------------------------------
Step "ESP-IDF 5.5" "the compiler for the CrossPad's chip - about 15 minutes the first time"
# An ESP-IDF 5.5 that is already here (EIM, the VS Code extension, a manual
# install) is used as it is. One of another version is left alone and 5.5 goes
# next to it. Only an ESP-IDF this installer made itself is ever repaired.
# IDF_TOOLS_PATH is set per command, never for the whole account: another
# ESP-IDF on this machine keeps working the way it did.
$findIdfPy = @'
import glob, json, os, re, sys
# Every ESP-IDF already on this machine, the one to use first.
# Prints JSON: {"use": {path, tools, version} or null, "others": ["5.3.1 at …", …]}
home = os.path.expanduser("~")
want = sys.argv[1] if len(sys.argv) > 1 else "5.5"
recorded = sys.argv[2] if len(sys.argv) > 2 else ""   # idf_tools_path from crosspad.local.json
found = []


def version(path):
    try:
        text = open(os.path.join(path, "tools", "cmake", "version.cmake"), encoding="utf-8").read()
    except OSError:
        return None
    parts = [re.search(r"IDF_VERSION_%s\s+(\d+)" % k, text) for k in ("MAJOR", "MINOR", "PATCH")]
    return ".".join(m.group(1) for m in parts) if all(parts) else None


def add(path, tools=None):
    if not path:
        return
    path = os.path.normpath(os.path.expanduser(path))
    if any(os.path.normcase(f[0]) == os.path.normcase(path) for f in found):
        return
    v = version(path)
    if v:
        found.append((path, tools, v))


add(os.environ.get("IDF_PATH"), os.environ.get("IDF_TOOLS_PATH"))
# The IDE / EIM records: esp_idf.json (VS Code extension, EIM) and eim_idf.json.
for tools_dir in (os.environ.get("IDF_TOOLS_PATH"), os.path.join(home, ".espressif"),
                  "C:/Espressif/tools", "C:/Espressif", "C:/esp/.espressif"):
    for name in ("esp_idf.json", "eim_idf.json"):
        try:
            cfg = json.load(open(os.path.join(tools_dir or "", name), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        installed = cfg.get("idfInstalled") or {}
        entries = installed.values() if isinstance(installed, dict) else installed
        selected = installed.get(cfg.get("idfSelectedId")) if isinstance(installed, dict) else None
        for e in ([selected] if selected else []) + list(entries):
            if isinstance(e, dict):
                add(e.get("path"), cfg.get("idfToolsPath") or tools_dir)
# Where people and installers usually put it.
for pattern in ("~/esp/esp-idf", "~/esp/v*/esp-idf", "~/esp/esp-idf-v*", "~/.espressif/v*/esp-idf",
                "/opt/esp-idf", "/opt/esp/idf", "C:/esp/esp-idf", "C:/esp/esp-idf-v*",
                "C:/Espressif/frameworks/esp-idf-v*", "~/esp-idf"):
    for p in sorted(glob.glob(os.path.expanduser(pattern)), reverse=True):
        add(p)
# The VS Code ESP-IDF extension's own setting.
for settings in ("~/.config/Code/User/settings.json",
                 "~/Library/Application Support/Code/User/settings.json",
                 os.path.join(os.environ.get("APPDATA", ""), "Code", "User", "settings.json")):
    try:
        s = json.load(open(os.path.expanduser(settings), encoding="utf-8"))
    except (OSError, ValueError):
        continue
    add(s.get("idf.espIdfPathWin") if os.name == "nt" else s.get("idf.espIdfPath"),
        s.get("idf.toolsPathWin") if os.name == "nt" else s.get("idf.toolsPath"))



def tools_for(path, version):
    """The tools directory that holds this ESP-IDF's Python environment: an
    install found without one (a folder by name) must not get a fresh set."""
    mm = ".".join(version.split(".")[:2])
    for t in (os.environ.get("IDF_TOOLS_PATH"), recorded,
              os.path.join(os.path.dirname(path), ".espressif"), os.path.join(home, ".espressif")):
        if t and glob.glob(os.path.join(t, "python_env", "idf%s_*" % mm)):
            return t
    return None


good = [f for f in found if f[2] == want or f[2].startswith(want + ".")]
use = max(good, key=lambda f: [int(x) for x in f[2].split(".")]) if good else None
print(json.dumps({
    "use": {"path": use[0], "tools": use[1] or tools_for(use[0], use[2]) or os.environ.get("IDF_TOOLS_PATH")
            or os.path.join(home, ".espressif"), "version": use[2]} if use else None,
    "others": [f"{v} at {p}" for p, _, v in found if not use or p != use[0]]}))
'@
$ownIdf = $true
if ($env:CROSSPAD_IDF_DIR) {
    if ((Test-Path $IdfDir) -and -not (Test-Path "$IdfDir\.crosspad-installed")) { $ownIdf = $false }
} else {
    $findIdfPy | Set-Content -Encoding UTF8 "$tmp\find_idf.py"
    $recorded = ""
    if (Test-Path "$CrossPadDir\crosspad.local.json") {
        try { $recorded = [string](Get-Content "$CrossPadDir\crosspad.local.json" -Raw | ConvertFrom-Json).idf_tools_path } catch {}
    }
    $found = (& python "$tmp\find_idf.py" 5.5 $recorded) | ConvertFrom-Json
    if ($found.use) {
        $IdfDir = $found.use.path; $IdfTools = $found.use.tools
        if (-not (Test-Path "$IdfDir\.crosspad-installed")) {
            $ownIdf = $false
            Note "found your ESP-IDF $($found.use.version) at $IdfDir - using it as it is"
        }
    } else {
        if ($found.others) { Note "found ESP-IDF $($found.others -join '; ') - CrossPad needs 5.5; it goes next to them, yours stay as they are" }
        if ((Test-Path $IdfDir) -and -not (Test-Path "$IdfDir\.crosspad-installed")) { $IdfDir = "C:\esp\esp-idf-v5.5" }
    }
}
$env:IDF_TOOLS_PATH = $IdfTools
function Idf-Ok { cmd /c "set `"IDF_TOOLS_PATH=$IdfTools`" && call `"$IdfDir\export.bat`" >nul 2>&1 && idf.py --version >nul 2>&1"; return $LASTEXITCODE -eq 0 }
if ($ownIdf) {
    if ((Test-Path $IdfDir) -and -not (Test-Path "$IdfDir\.git")) {
        $aside = "$IdfDir.broken-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Note "$IdfDir is not a working ESP-IDF - moving it to $aside"
        Move-Item $IdfDir $aside
    }
    if (-not (Test-Path $IdfDir)) {
        New-Item -ItemType Directory -Force (Split-Path $IdfDir) | Out-Null
        git -c advice.detachedHead=false clone --quiet --depth 1 --branch $IdfVersion --recursive --shallow-submodules https://github.com/espressif/esp-idf $IdfDir
        if ($LASTEXITCODE -ne 0) { Bad "ESP-IDF download failed" "check the connection and run this again"; exit 1 }
        New-Item -ItemType File -Force "$IdfDir\.crosspad-installed" | Out-Null
    }
}
$idfLog = "$tmp\idf-install.log"
if (-not (Idf-Ok)) {
    if ($ownIdf) {
        # Deleted or edited files inside our ESP-IDF come back from its own git.
        git -C $IdfDir checkout --quiet -- . 2>$null
        git -C $IdfDir submodule update --quiet --init --recursive --depth 1 2>$null
    }
    # install.bat only adds what is missing - safe on someone else's ESP-IDF too.
    cmd /c "`"$IdfDir\install.bat`" esp32s3" *> $idfLog
    if (-not (Idf-Ok) -and $ownIdf) {
        # A broken Python environment is the usual culprit; build it again.
        Remove-Item -Recurse -Force "$IdfTools\python_env\idf5.5_*" -ErrorAction SilentlyContinue
        cmd /c "`"$IdfDir\install.bat`" esp32s3" *>> $idfLog
    }
}
if (Idf-Ok) { Ok "ESP-IDF $(git -C $IdfDir describe --tags 2>$null) at $IdfDir" }
elseif (-not $ownIdf) { Bad "your ESP-IDF at $IdfDir does not start" "repair it with the tool you installed it with, or set CROSSPAD_IDF_DIR=C:\esp\crosspad-idf and run this again for a separate one" }
else { Bad "ESP-IDF did not install" "the details are in $idfLog - send it on Discord (#support)" }

# ---------------------------------------------------------------------------
Step "USB access" "Windows has the drivers built in"
Ok "nothing to do"
$lp = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -ErrorAction SilentlyContinue).LongPathsEnabled
if ($lp -ne 1) { Note "Windows long paths are off; the short folders above keep builds under the limit." }

# ---------------------------------------------------------------------------
Step "Test tools (optional)" "crosspad-hil: lets CP Tools and AI agents check the board automatically"
if ($env:CROSSPAD_NO_HIL) { Note "skipped" } else {
    $venv = "$CrossPadDir\.venv"
    if ((Test-Path "$venv\Scripts\crosspad-hil.exe")) {
        # It knows the firmware's commands, so it moves with the project.
        & "$venv\Scripts\pip.exe" install -q --upgrade "git+https://github.com/CrossPad/crosspad-hil" *> "$tmp\hil-install.log"
        if ($LASTEXITCODE -eq 0) { Ok "crosspad-hil (up to date)" } else { Note "crosspad-hil could not be updated - the one already here stays" }
    } else {
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
envs = sorted((p.name for p in (pathlib.Path(tools) / "python_env").glob("idf5.5_*_env")), reverse=True)
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
# ESP-IDF extension 2.x finds a setup only through EIM's records or these
# variables; idf.currentSetup must equal IDF_PATH for it to be the one used.
extra = settings.get("idf.customExtraVars") or {}
extra.update({"IDF_PATH": idf, "IDF_TOOLS_PATH": tools, "IDF_PYTHON_ENV_PATH": str(pathlib.Path(tools) / "python_env" / envs[0]) if envs else ""})
settings["idf.customExtraVars"] = extra
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
# A second repository next to the project (PC simulator, Arduino version):
# cloned once, then fast-forwarded when it carries nothing of yours.
function Clone-Or-Update($dir, $repo, $branch) {
    if ((Test-Path $dir) -and -not (Test-Path "$dir\.git")) { Move-Item $dir "$dir.broken-$(Get-Date -Format yyyyMMdd-HHmmss)" }
    if (-not (Test-Path $dir)) {
        git clone --quiet --branch $branch "https://github.com/$repo" $dir
        if ($LASTEXITCODE -ne 0) { return $false }
    } else {
        $changes = git -C $dir status --porcelain --ignore-submodules --untracked-files=no
        if (-not $changes) { git -C $dir pull --quiet --ff-only }
    }
    git -C $dir submodule update --quiet --init --recursive
    return $LASTEXITCODE -eq 0
}

if ($WithPc) {
    Step "PC simulator" "the CrossPad on this computer's screen - Visual Studio's C++ tools and SDL2, about 20 minutes"
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    function Find-Vcvars { if (Test-Path $vswhere) { & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -find "VC\Auxiliary\Build\vcvarsall.bat" | Select-Object -First 1 } }
    if (-not (Find-Vcvars)) {
        Note "Installing Visual Studio's C++ build tools (Windows asks once for permission)..."
        winget install --id Microsoft.VisualStudio.2022.BuildTools --exact --silent --accept-package-agreements --accept-source-agreements `
            --override "--quiet --wait --norestart --nocache --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.VC.CMake.Project --includeRecommended" *> "$tmp\vs-buildtools.log"
    }
    $vcvars = Find-Vcvars
    if (-not $vcvars) { Bad "Visual Studio's C++ build tools did not install" "details in $tmp\vs-buildtools.log" } else {
        Ok "C++ build tools"
        if (-not (Test-Path "C:\vcpkg\vcpkg.exe")) {
            if (-not (Test-Path "C:\vcpkg")) { git clone --quiet https://github.com/microsoft/vcpkg C:\vcpkg }
            cmd /c "C:\vcpkg\bootstrap-vcpkg.bat -disableMetrics" *> "$tmp\vcpkg.log"
        }
        cmd /c "C:\vcpkg\vcpkg.exe install sdl2:x64-windows" *>> "$tmp\vcpkg.log"
        if ($LASTEXITCODE -eq 0) { Ok "SDL2 (vcpkg)" } else { Bad "SDL2 did not install" "details in $tmp\vcpkg.log" }
        if (Clone-Or-Update $PcDir "CrossPad/crosspad-pc" $PcBranch) {
            Ok "crosspad-pc in $PcDir"
            # build.bat names Visual Studio Community; vswhere finds any edition.
            cmd /c "call `"$vcvars`" x64 >nul && cd /d `"$PcDir`" && cmake -B build -G Ninja -DCMAKE_TOOLCHAIN_FILE=C:/vcpkg/scripts/buildsystems/vcpkg.cmake -DCMAKE_BUILD_TYPE=Debug -DUSE_FREERTOS=ON && cmake --build build" *> "$tmp\pc-build.log"
            if ($LASTEXITCODE -eq 0 -and (Test-Path "$PcDir\bin\CrossPad.exe")) { Ok "the simulator is built - start it with: crosspad-sim" }
            else { Bad "the PC simulator did not build" "details in $tmp\pc-build.log - send it on Discord (#support)" }
        } else { Bad "crosspad-pc did not download" "check the connection and run this again" }
    }
}

if ($WithArduino) {
    Step "Arduino version" "PlatformIO and the Arduino firmware - about 10 minutes"
    $pio = "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe"
    if (-not (Test-Path $pio)) {
        # PlatformIO's own installer: a private Python environment, no admin.
        Download "https://raw.githubusercontent.com/platformio/platformio-core-installer/master/get-platformio.py" "$tmp\get-platformio.py"
        & python "$tmp\get-platformio.py" *> "$tmp\pio-install.log"
    }
    if (Test-Path $pio) {
        Ok "PlatformIO $((& $pio --version) -replace '.* ','')"
        if (Clone-Or-Update $ArduinoDir "CrossPad/ESP32-S3" $ArduinoBranch) {
            Ok "ESP32-S3 (Arduino) in $ArduinoDir"
            Push-Location $ArduinoDir
            # crosspad_v2 is the 2.0 board; crosspad_rev2 is the older 1.9 one,
            # and the only one a branch without crosspad_v2 knows.
            $pioEnv = if (Select-String -Quiet -Pattern '^\[env:crosspad_v2\]' "$ArduinoDir\platformio.ini") { "crosspad_v2" } else { "crosspad_rev2" }
            & $pio run -e $pioEnv *> "$tmp\arduino-build.log"
            $built = $LASTEXITCODE -eq 0
            Pop-Location
            if ($built) { Ok "the Arduino firmware builds" } else { Bad "the Arduino firmware did not build" "details in $tmp\arduino-build.log" }
        } else { Bad "the Arduino project did not download" "it needs access to CrossPad/ESP32-S3 - ask on Discord" }
    } else { Bad "PlatformIO did not install" "details in $tmp\pio-install.log" }
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
# idf.py runs in the project, so a relative -B build_v2 / -DSDKCONFIG=sdkconfig.v2 lands there.
Shim "crosspad-idf" "cd /d `"$CrossPadDir`" && idf.py"
if (Test-Path "$CrossPadDir\.venv\Scripts\crosspad-hil.exe") { Shim "crosspad-hil" "`"$CrossPadDir\.venv\Scripts\crosspad-hil.exe`"" }
if (Test-Path "$PcDir\bin\CrossPad.exe") {   # the simulator runs from its own folder
    "@echo off`r`nrem crosspad-sim - written by the CrossPad installer`r`ncd /d `"$PcDir`" && bin\CrossPad.exe %*" | Set-Content -Encoding ASCII "$bin\crosspad-sim.cmd"
}
if (Test-Path "$PcDir\scripts") { Shim "crosspad-pc" "python `"$PcDir\scripts\app_manager.py`"" }
if (Test-Path "$ArduinoDir\scripts") { Shim "crosspad-arduino" "python `"$ArduinoDir\scripts\app_manager.py`"" }
if (Test-Path "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe") { Shim "pio" "`"$env:USERPROFILE\.platformio\penv\Scripts\pio.exe`"" }
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
& python -c "import json,sys,pathlib; p=pathlib.Path(sys.argv[1]); c=json.loads(p.read_text()) if p.exists() else {}; c['idf_path']=sys.argv[2]; c['idf_tools_path']=sys.argv[3]; p.write_text(json.dumps(c, indent=2)+chr(10))" "$CrossPadDir\crosspad.local.json" $IdfDir $IdfTools
Add-UserPath $bin
Ok "$((Get-ChildItem $bin -Name) -replace '\.cmd$','' -join ' ') - from any new terminal"
try {
    $sh = (New-Object -ComObject WScript.Shell).CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\CP Tools.lnk")
    $sh.TargetPath = $launcher; $sh.WorkingDirectory = $CrossPadDir; $sh.Save()
    Ok "desktop shortcut 'CP Tools'"
} catch { Note "no desktop shortcut - open $launcher instead" }
# FL Studio reads controller scripts from Documents\Image-Line; with FL on this
# computer the DAW Control script goes there, so FL finds the board by itself.
$flHw = Join-Path ([Environment]::GetFolderPath('MyDocuments')) "Image-Line\FL Studio\Settings\Hardware"
$flScript = "$CrossPadDir\components\crosspad-dawcontrol\host\fl_studio"
if (((Test-Path "$env:ProgramFiles\Image-Line") -or (Test-Path $flHw)) -and (Test-Path "$flScript\device_CrossPad.py")) {
    New-Item -ItemType Directory -Force "$flHw\CrossPad" | Out-Null
    Copy-Item "$flScript\*" "$flHw\CrossPad\" -Recurse -Force
    Ok "FL Studio's CrossPad script - FL picks the board up on its next start"
}

# ---------------------------------------------------------------------------
Step "Final check" "in a new terminal, the way you will use it"
Refresh-Path              # exactly the PATH a new window gets from the registry
foreach ($t in @("git", "python", "gh", "code", "node", "npx") + ((Get-ChildItem $bin -Name) -replace '\.cmd$','')) {
    if ($t -eq "code" -and $env:CROSSPAD_NO_VSCODE) { continue }
    if (($t -eq "node" -or $t -eq "npx") -and $env:CROSSPAD_NO_MCP) { continue }
    $found = powershell -NoProfile -Command "[bool](Get-Command $t -ErrorAction SilentlyContinue)"
    if ($found -eq "True") { Ok "$t is on PATH" } else { Bad "$t is not on PATH in a new terminal" "open a new terminal and run this installer again" }
}
cmd /c "set `"IDF_TOOLS_PATH=$IdfTools`" && call `"$IdfDir\export.bat`" >nul 2>&1 && idf.py --version >nul 2>&1"
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
