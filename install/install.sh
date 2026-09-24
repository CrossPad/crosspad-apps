#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# CrossPad setup for Linux and macOS — one command, then CP Tools opens.
#
#   curl -fsSL https://raw.githubusercontent.com/CrossPad/crosspad-apps/main/install/install.sh | bash
#
# Safe to run again at any time: every step checks what is already there and
# only installs or repairs what is missing or broken. Nothing you changed in
# the project is overwritten.
#
# Options (environment variables):
#   CROSSPAD_DIR=~/CrossPad        where the project goes
#   CROSSPAD_BRANCH=crosspad_v20   which branch of CrossPad/platform-idf
#   CROSSPAD_IDF_DIR=~/esp/esp-idf where ESP-IDF goes (default: an ESP-IDF 5.5 already here, else this)
#   CROSSPAD_YES=1                 answer yes to every question (extras stay off)
#   CROSSPAD_WITH_PC=1             also set up the PC simulator (~/CrossPad-PC)
#   CROSSPAD_WITH_ARDUINO=1        also set up the Arduino version (~/CrossPad-Arduino)
#   CROSSPAD_NO_HIL=1 / CROSSPAD_NO_VSCODE=1 / CROSSPAD_NO_MCP=1 / CROSSPAD_NO_TUI=1
#                                  skip the test tools, VS Code, the AI tools, opening CP Tools

set -u

CROSSPAD_DIR="${CROSSPAD_DIR:-$HOME/CrossPad}"
CROSSPAD_BRANCH="${CROSSPAD_BRANCH:-crosspad_v20}"
CROSSPAD_REPO="CrossPad/platform-idf"
IDF_DIR="${CROSSPAD_IDF_DIR:-$HOME/esp/esp-idf}"
IDF_VERSION="v5.5.5"          # what CI builds with
IDF_TARGET="esp32s3"
PC_DIR="${CROSSPAD_PC_DIR:-$HOME/CrossPad-PC}"
# The simulator and the Arduino version live on their development branches:
# master/main there predate the app manager and the 2.0 board.
PC_BRANCH="${CROSSPAD_PC_BRANCH:-feat/virtual-audio-on-pipeline}"
ARDUINO_DIR="${CROSSPAD_ARDUINO_DIR:-$HOME/CrossPad-Arduino}"
ARDUINO_BRANCH="${CROSSPAD_ARDUINO_BRANCH:-feat/audio-module-arduino}"
WITH_PC="${CROSSPAD_WITH_PC:-}"
WITH_ARDUINO="${CROSSPAD_WITH_ARDUINO:-}"

STEPS=10
step_no=0
failed=()

bold=$'\033[1m'; green=$'\033[32m'; red=$'\033[31m'; yellow=$'\033[33m'; gray=$'\033[90m'; off=$'\033[0m'
if [ -n "${NO_COLOR:-}" ] || [ ! -t 1 ]; then bold=; green=; red=; yellow=; gray=; off=; fi

step() { step_no=$((step_no + 1)); printf '\n%sStep %d of %d: %s%s\n' "$bold" "$step_no" "$STEPS" "$1" "$off"; [ -n "${2:-}" ] && printf '%s  %s%s\n' "$gray" "$2" "$off"; }
ok()   { printf '  %s✓%s %s\n' "$green" "$off" "$1"; }
bad()  { printf '  %s✗%s %s\n' "$red" "$off" "$1"; [ -n "${2:-}" ] && printf '    → %s\n' "$2"; failed+=("$1"); }
note() { printf '  %s%s%s\n' "$gray" "$1" "$off"; }
have() { command -v "$1" >/dev/null 2>&1; }

# Reading answers from the terminal even when the script itself arrives on stdin (curl | bash).
ask() {
    if [ -n "${CROSSPAD_YES:-}" ]; then return 0; fi
    local reply
    printf '  %s [Y/n] ' "$1"
    read -r reply </dev/tty || reply=y
    case "$reply" in n|N|no|No) return 1 ;; *) return 0 ;; esac
}

ask_no() {   # an optional extra: only an explicit yes
    [ -n "${CROSSPAD_YES:-}" ] && return 1
    local reply
    printf '  %s [y/N] ' "$1"
    read -r reply </dev/tty || reply=n
    case "$reply" in y|Y|yes|Yes|t|T|tak) return 0 ;; *) return 1 ;; esac
}

os="$(uname -s)"
pkg=""
if [ "$os" = "Linux" ]; then
    if have apt-get; then pkg=apt; elif have dnf; then pkg=dnf; elif have pacman; then pkg=pacman; elif have zypper; then pkg=zypper; fi
fi
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

install_pkgs() {   # install_pkgs <apt names> -- <dnf names> -- <pacman names> -- <zypper names>
    local apt=() dnf=() pac=() zyp=() which=apt
    for a in "$@"; do
        if [ "$a" = "--" ]; then case $which in apt) which=dnf;; dnf) which=pac;; pac) which=zyp;; esac; continue; fi
        case $which in apt) apt+=("$a");; dnf) dnf+=("$a");; pac) pac+=("$a");; zyp) zyp+=("$a");; esac
    done
    case "$pkg" in
        apt)    $SUDO apt-get update -qq && $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${apt[@]}" ;;
        dnf)    $SUDO dnf install -y -q "${dnf[@]}" ;;
        pacman) $SUDO pacman -S --needed --noconfirm "${pac[@]}" ;;
        zypper) $SUDO zypper -n -q install "${zyp[@]}" ;;
        *) return 1 ;;
    esac
}

printf '%sCrossPad setup%s\n' "$bold" "$off"
printf 'This installs what the CrossPad tools need and opens CP Tools.\n'
printf 'It takes 15–30 minutes the first time (mostly downloading), a minute after that.\n'
printf 'Project folder: %s\n' "$CROSSPAD_DIR"
case "$CROSSPAD_DIR$IDF_DIR" in
    *" "*) bad "The folders must not contain spaces (ESP-IDF cannot build there)" \
               "run again with CROSSPAD_DIR=/some/path/without/spaces"; exit 1 ;;
esac
if [ -z "$WITH_PC$WITH_ARDUINO" ] && [ -z "${CROSSPAD_YES:-}" ]; then
    printf '\nOptional — answer now, then you can leave it running:\n'
    ask_no "Also set up the PC simulator (the CrossPad on this computer's screen)?" && WITH_PC=1
    ask_no "Also set up the Arduino (PlatformIO) version of the firmware?" && WITH_ARDUINO=1
fi
[ -n "$WITH_PC" ] && STEPS=$((STEPS + 1))
[ -n "$WITH_ARDUINO" ] && STEPS=$((STEPS + 1))

# ---------------------------------------------------------------------------
step "Basic tools" "git, Python 3, and the programs the firmware build uses"
if [ "$os" = "Darwin" ]; then
    if ! xcode-select -p >/dev/null 2>&1; then
        note "macOS asks to install the Command Line Tools — click Install, wait, then run this again."
        xcode-select --install 2>/dev/null
        exit 1
    fi
    if ! have brew; then
        if ask "Homebrew (the macOS package manager) is not installed. Install it?"; then
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/tty
            [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
            [ -x /usr/local/bin/brew ] && eval "$(/usr/local/bin/brew shellenv)"
        fi
    fi
    if have brew; then
        brew install -q git cmake ninja dfu-util python3 gh >/dev/null 2>&1 || true
    fi
elif [ -n "$pkg" ]; then
    missing=0
    for t in git python3 cmake ninja wget flex bison gperf dfu-util; do have "$t" || missing=1; done
    python3 -c "import venv, ensurepip" 2>/dev/null || missing=1
    if [ $missing -eq 1 ]; then
        note "Installing packages with $pkg (your password may be asked once)."
        install_pkgs git wget flex bison gperf python3 python3-pip python3-venv cmake ninja-build ccache libffi-dev libssl-dev dfu-util libusb-1.0-0 \
            -- git wget flex bison gperf python3 python3-pip cmake ninja-build ccache libffi-devel openssl-devel dfu-util libusb1 \
            -- git wget flex bison gperf python python-pip cmake ninja ccache libffi openssl dfu-util libusb \
            -- git wget flex bison gperf python3 python3-pip cmake ninja ccache libffi-devel libopenssl-devel dfu-util libusb-1_0-0 \
            || bad "Some packages did not install" "install them with your package manager and run this again"
    fi
else
    note "Unknown package manager — install git, python3, cmake, ninja, flex, bison, gperf, dfu-util yourself."
fi
for t in git python3; do
    if have "$t"; then ok "$t"; else bad "$t is missing" "install $t and run this again"; exit 1; fi
done
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    bad "Python $(python3 -V 2>&1) is too old — 3.10 or newer is needed" "install a newer python3"; exit 1
fi
ok "Python $(python3 -c 'import platform; print(platform.python_version())')"

# ---------------------------------------------------------------------------
step "GitHub" "the CrossPad project is shared through GitHub"
if ! have gh; then
    if [ "$os" = "Linux" ]; then
        case "$pkg" in
            apt) if ! apt-cache show gh >/dev/null 2>&1; then
                     $SUDO mkdir -p -m 755 /etc/apt/keyrings
                     wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg | $SUDO tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
                     echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
                         | $SUDO tee /etc/apt/sources.list.d/github-cli.list >/dev/null
                 fi
                 install_pkgs gh -- gh -- github-cli -- gh ;;
            *) install_pkgs gh -- gh -- github-cli -- gh ;;
        esac
    fi
fi
if have gh; then ok "GitHub CLI"; else bad "GitHub CLI (gh) is missing" "https://cli.github.com — install it and run this again"; fi

# The project repository is private until the CrossPad OS is open: cloning it
# needs a GitHub account with access. Reading apps does not. The probe never
# prompts: git would ask for a user name, or open a credential manager's own
# sign-in window, and the user would sign in twice.
can_see_repo() {
    GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never git -c credential.helper= \
        -c 'credential.https://github.com.helper=!gh auth git-credential' \
        ls-remote "https://github.com/$CROSSPAD_REPO" HEAD >/dev/null 2>&1
}
# git itself must use the gh sign-in for github.com (clone, submodules, pip).
if have gh && gh auth status >/dev/null 2>&1; then
    gh auth setup-git >/dev/null 2>&1 || true
fi
if can_see_repo; then
    ok "CrossPad project is reachable"
elif have gh; then
    if ! gh auth status >/dev/null 2>&1; then
        note "Sign in to GitHub: a code appears below, your browser opens, paste the code there."
        gh auth login --hostname github.com --git-protocol https --web </dev/tty || true
    fi
    gh auth setup-git >/dev/null 2>&1 || true
    if can_see_repo; then
        ok "Signed in to GitHub as $(gh api user --jq .login 2>/dev/null)"
    else
        bad "Your GitHub account can't see $CROSSPAD_REPO yet" \
            "ask for access on the CrossPad Discord with your GitHub user name, then run this again"
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
step "The CrossPad project" "$CROSSPAD_DIR"
if [ -d "$CROSSPAD_DIR" ] && ! git -C "$CROSSPAD_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    aside="$CROSSPAD_DIR.broken-$(date +%Y%m%d-%H%M%S)"
    note "$CROSSPAD_DIR exists but is not a working project — moving it to $aside"
    mv "$CROSSPAD_DIR" "$aside"
fi
if [ ! -d "$CROSSPAD_DIR" ]; then
    git clone --branch "$CROSSPAD_BRANCH" "https://github.com/$CROSSPAD_REPO" "$CROSSPAD_DIR" \
        || { bad "Download failed" "check the connection and run this again"; exit 1; }
else
    # Only edits to tracked files are "yours": the launcher and .venv this
    # script writes into the folder are untracked and must not block updates.
    if [ -z "$(git -C "$CROSSPAD_DIR" status --porcelain --ignore-submodules --untracked-files=no)" ]; then
        git -C "$CROSSPAD_DIR" pull --ff-only --quiet || note "left the project as it is (it has its own commits)"
    else
        note "the project has changes of yours — not updating it, only filling in what is missing"
    fi
fi
# Missing or half-downloaded components come back; ones with your work are left alone.
git -C "$CROSSPAD_DIR" submodule update --init --recursive \
    && ok "project and its components" \
    || bad "some components did not download" "run this again; if it keeps failing, [3] Something's wrong in CP Tools"

# ---------------------------------------------------------------------------
step "ESP-IDF 5.5" "the compiler for the CrossPad's chip — about 10 minutes the first time"
IDF_TOOLS="${IDF_TOOLS_PATH:-$HOME/.espressif}"
idf_ok() { ( export IDF_TOOLS_PATH="$IDF_TOOLS"; . "$IDF_DIR/export.sh" >/dev/null 2>&1 && idf.py --version >/dev/null 2>&1 ); }
# An ESP-IDF 5.5 that is already here (EIM, the VS Code extension, a manual
# install) is used as it is. One of another version is left alone and 5.5 goes
# next to it. Only an ESP-IDF this installer made itself is ever repaired.
recorded_tools="$(python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("idf_tools_path", ""))
except Exception: print("")' "$CROSSPAD_DIR/crosspad.local.json")"
idf_found="$(python3 - 5.5 "$recorded_tools" <<'FINDIDF'
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
FINDIDF
)"
own_idf=1
# An ESP-IDF named by CROSSPAD_IDF_DIR that this installer did not make is used as it is.
[ -n "${CROSSPAD_IDF_DIR:-}" ] && [ -e "$IDF_DIR" ] && [ ! -e "$IDF_DIR/.crosspad-installed" ] && own_idf=0
if [ -z "${CROSSPAD_IDF_DIR:-}" ] && [ -n "$idf_found" ]; then
    use_path=$(python3 -c 'import json,sys; u=json.loads(sys.argv[1])["use"]; print(u["path"] if u else "")' "$idf_found")
    others=$(python3 -c 'import json,sys; print("; ".join(json.loads(sys.argv[1])["others"]))' "$idf_found")
    if [ -n "$use_path" ]; then
        IDF_DIR="$use_path"
        IDF_TOOLS=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["use"]["tools"])' "$idf_found")
        [ -e "$IDF_DIR/.crosspad-installed" ] || own_idf=0
        [ $own_idf -eq 0 ] && note "found your ESP-IDF $(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["use"]["version"])' "$idf_found") at $IDF_DIR — using it as it is"
    else
        [ -n "$others" ] && note "found ESP-IDF $others — CrossPad needs 5.5; it goes next to them, yours stay as they are"
        if [ -e "$IDF_DIR" ] && [ ! -e "$IDF_DIR/.crosspad-installed" ]; then
            IDF_DIR="$HOME/esp/esp-idf-v5.5"
        fi
    fi
fi
if [ $own_idf -eq 1 ]; then
    if [ -d "$IDF_DIR" ] && ! git -C "$IDF_DIR" rev-parse --git-dir >/dev/null 2>&1; then
        aside="$IDF_DIR.broken-$(date +%Y%m%d-%H%M%S)"
        note "$IDF_DIR is not a working ESP-IDF — moving it to $aside"
        mv "$IDF_DIR" "$aside"
    fi
    if [ ! -d "$IDF_DIR" ]; then
        mkdir -p "$(dirname "$IDF_DIR")"
        git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$IDF_VERSION" --recursive --shallow-submodules \
            https://github.com/espressif/esp-idf "$IDF_DIR" \
            || { bad "ESP-IDF download failed" "check the connection and run this again"; exit 1; }
        touch "$IDF_DIR/.crosspad-installed"
    fi
fi
if ! idf_ok; then
    if [ $own_idf -eq 1 ]; then
        # Deleted or edited files inside our ESP-IDF come back from its own git.
        git -C "$IDF_DIR" checkout --quiet -- . 2>/dev/null
        git -C "$IDF_DIR" submodule update --quiet --init --recursive --depth 1 2>/dev/null
    fi
    # install.sh only adds what is missing — safe on someone else's ESP-IDF too.
    IDF_TOOLS_PATH="$IDF_TOOLS" "$IDF_DIR/install.sh" "$IDF_TARGET" >/tmp/crosspad-idf-install.log 2>&1
    if ! idf_ok && [ $own_idf -eq 1 ]; then
        # A broken Python environment is the usual culprit; build it again.
        rm -rf "$IDF_TOOLS/python_env/idf5.5_"*
        IDF_TOOLS_PATH="$IDF_TOOLS" "$IDF_DIR/install.sh" "$IDF_TARGET" >>/tmp/crosspad-idf-install.log 2>&1
    fi
fi
if idf_ok; then ok "ESP-IDF $(git -C "$IDF_DIR" describe --tags 2>/dev/null || echo 5.5) at $IDF_DIR"
elif [ $own_idf -eq 0 ]; then
    bad "your ESP-IDF at $IDF_DIR does not start" \
        "repair it with the tool you installed it with, or run this installer with CROSSPAD_IDF_DIR=$HOME/esp/crosspad-idf for a separate one"
else bad "ESP-IDF did not install" "the details are in /tmp/crosspad-idf-install.log — send it on Discord (#support)"; fi

# ---------------------------------------------------------------------------
step "USB access" "so the tools can talk to the board"
if [ "$os" = "Linux" ]; then
    grp=dialout; getent group uucp >/dev/null && ! getent group dialout >/dev/null && grp=uucp
    if id -nG "$USER" | tr ' ' '\n' | grep -qx "$grp"; then
        ok "you are in the $grp group"
    elif ask "Allow your user to use USB serial devices (adds you to '$grp')?"; then
        $SUDO usermod -aG "$grp" "$USER" && ok "added — log out and back in once for it to take effect" \
            || bad "could not add you to $grp" "sudo usermod -aG $grp $USER"
    fi
else
    ok "nothing to do on macOS"
fi

# ---------------------------------------------------------------------------
step "Test tools (optional)" "crosspad-hil: lets CP Tools and AI agents check the board automatically"
if [ -n "${CROSSPAD_NO_HIL:-}" ]; then
    note "skipped"
else
    venv="$CROSSPAD_DIR/.venv"
    if [ -x "$venv/bin/crosspad-hil" ] && "$venv/bin/crosspad-hil" --help >/dev/null 2>&1; then
        # It knows the firmware's commands, so it moves with the project.
        if "$venv/bin/pip" install -q --upgrade "git+https://github.com/CrossPad/crosspad-hil" >/tmp/crosspad-hil-install.log 2>&1; then
            ok "crosspad-hil (up to date)"
        else
            note "crosspad-hil could not be updated — the one already here stays"
        fi
    else
        rm -rf "$venv"
        if python3 -m venv "$venv" && "$venv/bin/pip" install -q "git+https://github.com/CrossPad/crosspad-hil" >/tmp/crosspad-hil-install.log 2>&1; then
            ok "crosspad-hil"
        else
            note "crosspad-hil could not be installed (it needs access to CrossPad/crosspad-hil) — CP Tools works without it"
        fi
    fi
fi

# ---------------------------------------------------------------------------
step "VS Code" "the editor, with the ESP-IDF extension and the CP Tools buttons"
vscode_settings() {   # write this machine's real paths into .vscode/settings.json (merged)
    python3 - "$CROSSPAD_DIR" "$IDF_DIR" "$IDF_TOOLS" <<'PY'
import json, pathlib, re, sys
proj, idf, tools = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
vs = proj / ".vscode"
envs = sorted((p.name for p in (pathlib.Path(tools) / "python_env").glob("idf5.5_*_env")), reverse=True)
py = f"{tools}/python_env/{envs[0]}/bin/python" if envs else "python3"
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
extra.update({"IDF_PATH": idf, "IDF_TOOLS_PATH": tools, "IDF_PYTHON_ENV_PATH": f"{tools}/python_env/{envs[0]}" if envs else ""})
settings["idf.customExtraVars"] = extra
vs.mkdir(exist_ok=True)
out.write_text(json.dumps(settings, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}
if [ -n "${CROSSPAD_NO_VSCODE:-}" ]; then
    note "skipped"
else
    if ! have code; then
        if [ "$os" = "Darwin" ] && have brew; then
            brew install -q --cask visual-studio-code >/dev/null 2>&1
        elif [ "$pkg" = "apt" ]; then
            note "Installing VS Code from Microsoft's package repository."
            install_pkgs gpg -- gnupg2 -- gnupg -- gpg2 >/dev/null 2>&1
            $SUDO mkdir -p -m 755 /etc/apt/keyrings
            wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor \
                | $SUDO tee /etc/apt/keyrings/packages.microsoft.gpg >/dev/null
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/packages.microsoft.gpg] https://packages.microsoft.com/repos/code stable main" \
                | $SUDO tee /etc/apt/sources.list.d/vscode.list >/dev/null
            install_pkgs code >/dev/null 2>&1
        elif [ "$pkg" = "dnf" ]; then
            note "Installing VS Code from Microsoft's package repository."
            $SUDO rpm --import https://packages.microsoft.com/keys/microsoft.asc
            printf '[code]\nname=Visual Studio Code\nbaseurl=https://packages.microsoft.com/yumrepos/vscode\nenabled=1\ngpgcheck=1\ngpgkey=https://packages.microsoft.com/keys/microsoft.asc\n' \
                | $SUDO tee /etc/yum.repos.d/vscode.repo >/dev/null
            $SUDO dnf install -y -q code >/dev/null 2>&1
        elif have snap; then
            $SUDO snap install --classic code >/dev/null 2>&1
        fi
    fi
    if have code; then
        code --install-extension espressif.esp-idf-extension --install-extension ms-vscode.cpptools \
             --install-extension spencerwmiles.vscode-task-buttons --force >/tmp/crosspad-vscode.log 2>&1 \
            && ok "VS Code with the ESP-IDF, C/C++ and task-button extensions" \
            || bad "VS Code extensions did not install" "details in /tmp/crosspad-vscode.log"
        vscode_settings && ok "VS Code settings point at ESP-IDF ($IDF_DIR)"
    else
        bad "VS Code did not install" "get it from https://code.visualstudio.com and run this again"
    fi
fi

# ---------------------------------------------------------------------------
step "AI assistant tools" "Node.js and the CrossPad MCP server, for VS Code and Claude Code"
mcp_config() {   # .vscode/mcp.json, merged: the server knows this project and ESP-IDF
    python3 - "$CROSSPAD_DIR" "$IDF_DIR" <<'PY'
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
PY
}
mcp_answers() {   # start the server the way an editor does and ask for its tools
    python3 - "$CROSSPAD_DIR" "$IDF_DIR" <<'PY'
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
PY
}
node_ok() { have node && node -e 'process.exit(parseInt(process.versions.node) >= 18 ? 0 : 1)' 2>/dev/null; }
if [ -n "${CROSSPAD_NO_MCP:-}" ]; then
    note "skipped"
else
    if ! node_ok; then
        if [ "$os" = "Darwin" ] && have brew; then brew install -q node >/dev/null 2>&1
        else install_pkgs nodejs npm -- nodejs npm -- nodejs npm -- nodejs npm >/dev/null 2>&1; fi
    fi
    if node_ok && have npx; then
        ok "Node.js $(node --version)"
        mcp_config && ok "VS Code knows the CrossPad MCP server (.vscode/mcp.json)"
        if have claude; then
            claude mcp get crosspad >/dev/null 2>&1 \
                || claude mcp add --scope user crosspad -e "CROSSPAD_IDF_ROOT=$CROSSPAD_DIR" \
                       -e "IDF_PATH=$IDF_DIR" -- npx -y crosspad-mcp-server@latest >/dev/null 2>&1
            claude mcp get crosspad >/dev/null 2>&1 && ok "Claude Code knows it too"
        fi
        if n=$(mcp_answers); then ok "the MCP server starts and offers $n tools"
        else bad "the MCP server did not answer" "run: npx -y crosspad-mcp-server@latest — and send what it prints on Discord (#support)"; fi
    else
        bad "Node.js 18 or newer is missing" "install it from https://nodejs.org and run this again"
    fi
fi

# ---------------------------------------------------------------------------
# A second repository next to the project (PC simulator, Arduino version):
# cloned once, then fast-forwarded when it carries nothing of yours.
clone_or_update() {   # clone_or_update DIR OWNER/REPO BRANCH
    local dir="$1" repo="$2" branch="$3"
    if [ -d "$dir" ] && ! git -C "$dir" rev-parse --git-dir >/dev/null 2>&1; then
        mv "$dir" "$dir.broken-$(date +%Y%m%d-%H%M%S)"
    fi
    if [ ! -d "$dir" ]; then
        git clone --quiet --branch "$branch" "https://github.com/$repo" "$dir" || return 1
    elif [ -z "$(git -C "$dir" status --porcelain --ignore-submodules --untracked-files=no)" ]; then
        git -C "$dir" pull --quiet --ff-only || true
    fi
    git -C "$dir" submodule update --quiet --init --recursive
}

if [ -n "$WITH_PC" ]; then
    step "PC simulator" "the CrossPad on this computer's screen — about 5 minutes"
    if [ "$os" = "Darwin" ]; then
        brew install -q sdl2 cmake ninja pkg-config >/dev/null 2>&1
    else
        install_pkgs build-essential cmake ninja-build libsdl2-dev pkg-config \
            -- gcc-c++ make cmake ninja-build SDL2-devel pkgconf \
            -- base-devel cmake ninja sdl2 pkgconf \
            -- gcc-c++ make cmake ninja libSDL2-devel pkg-config >/dev/null 2>&1
    fi
    if clone_or_update "$PC_DIR" "CrossPad/crosspad-pc" "$PC_BRANCH"; then
        ok "crosspad-pc in $PC_DIR"
        if (cd "$PC_DIR" && cmake -B build -G Ninja -DUSE_FREERTOS=ON -DCMAKE_BUILD_TYPE=Debug \
                && cmake --build build) >/tmp/crosspad-pc-build.log 2>&1 && [ -x "$PC_DIR/bin/CrossPad" ]; then
            ok "the simulator is built — start it with: crosspad-sim"
        else
            bad "the PC simulator did not build" "details in /tmp/crosspad-pc-build.log — send it on Discord (#support)"
        fi
    else
        bad "crosspad-pc did not download" "check the connection and run this again"
    fi
fi

if [ -n "$WITH_ARDUINO" ]; then
    step "Arduino version" "PlatformIO and the Arduino firmware — about 10 minutes"
    PIO="$HOME/.platformio/penv/bin/pio"
    if [ ! -x "$PIO" ]; then
        # PlatformIO's own installer: a private Python environment, no admin.
        curl -fsSL -o /tmp/get-platformio.py https://raw.githubusercontent.com/platformio/platformio-core-installer/master/get-platformio.py \
            && python3 /tmp/get-platformio.py >/tmp/crosspad-pio-install.log 2>&1
    fi
    if [ -x "$PIO" ]; then
        ok "PlatformIO $("$PIO" --version 2>/dev/null | awk '{print $NF}')"
        if clone_or_update "$ARDUINO_DIR" "CrossPad/ESP32-S3" "$ARDUINO_BRANCH"; then
            ok "ESP32-S3 (Arduino) in $ARDUINO_DIR"
            # crosspad_v2 is the 2.0 board; crosspad_rev2 is the older 1.9 one,
            # and the only one a branch without crosspad_v2 knows.
            pio_env=crosspad_rev2
            grep -q '^\[env:crosspad_v2\]' "$ARDUINO_DIR/platformio.ini" 2>/dev/null && pio_env=crosspad_v2
            if (cd "$ARDUINO_DIR" && "$PIO" run -e "$pio_env") >/tmp/crosspad-arduino-build.log 2>&1; then
                ok "the Arduino firmware builds"
            else
                bad "the Arduino firmware did not build" "details in /tmp/crosspad-arduino-build.log"
            fi
        else
            bad "the Arduino project did not download" "it needs access to CrossPad/ESP32-S3 — ask on Discord"
        fi
    else
        bad "PlatformIO did not install" "details in /tmp/crosspad-pio-install.log"
    fi
fi

# ---------------------------------------------------------------------------
step "CP Tools" "cptools and the crosspad-* commands, in any terminal"
# One small script per command: each sets up ESP-IDF itself, so nobody has to
# remember `. export.sh` or a path into tools/. They live in the project's bin/
# and are linked into ~/.local/bin.
bin="$CROSSPAD_DIR/bin"
mkdir -p "$bin"
shim() {   # shim NAME TARGET...  — TARGET run with the user's arguments
    local name="$1"; shift
    {
        echo '#!/usr/bin/env bash'
        echo "# $name — written by the CrossPad installer"
        echo "export IDF_TOOLS_PATH=\"$IDF_TOOLS\""
        echo ". \"$IDF_DIR/export.sh\" >/dev/null 2>&1"
        echo "exec $* \"\$@\""
    } > "$bin/$name"
    chmod +x "$bin/$name"
}
shim cptools          python3 "\"$CROSSPAD_DIR/tools/app_manager.py\""
shim crosspad-flash   python3 "\"$CROSSPAD_DIR/tools/ota_flash.py\""
shim crosspad-files   python3 "\"$CROSSPAD_DIR/tools/fs_transfer.py\""
shim crosspad-bench   python3 "\"$CROSSPAD_DIR/tools/bench.py\""
shim crosspad-board   python3 "\"$CROSSPAD_DIR/tools/crosspad_board.py\""
shim crosspad-idf     idf.py -C "\"$CROSSPAD_DIR\""
[ -x "$CROSSPAD_DIR/.venv/bin/crosspad-hil" ] && shim crosspad-hil "\"$CROSSPAD_DIR/.venv/bin/crosspad-hil\""
if [ -x "$PC_DIR/bin/CrossPad" ]; then   # the simulator runs from its own folder
    printf '#!/usr/bin/env bash\n# crosspad-sim — written by the CrossPad installer\ncd "%s" && exec bin/CrossPad "$@"\n' "$PC_DIR" > "$bin/crosspad-sim"
    chmod +x "$bin/crosspad-sim"
fi
[ -d "$PC_DIR/scripts" ] && shim crosspad-pc python3 "\"$PC_DIR/scripts/app_manager.py\""
[ -d "$ARDUINO_DIR/scripts" ] && shim crosspad-arduino python3 "\"$ARDUINO_DIR/scripts/app_manager.py\""
[ -x "$HOME/.platformio/penv/bin/pio" ] && shim pio "\"$HOME/.platformio/penv/bin/pio\""
# cptools with no arguments opens the TUI (the app manager's own default).
ln -sf "$bin/cptools" "$CROSSPAD_DIR/cptools"
python3 -c 'import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
try:
    cfg = json.loads(p.read_text())
except (OSError, ValueError):
    cfg = {}
cfg["idf_path"] = sys.argv[2]
cfg["idf_tools_path"] = sys.argv[3]
p.write_text(json.dumps(cfg, indent=2) + "\n")' "$CROSSPAD_DIR/crosspad.local.json" "$IDF_DIR" "$IDF_TOOLS"
mkdir -p "$HOME/.local/bin"
for f in "$bin"/*; do ln -sf "$f" "$HOME/.local/bin/$(basename "$f")"; done
if ! bash -lc 'command -v cptools' >/dev/null 2>&1; then
    # ~/.local/bin is not on a login PATH yet (macOS, some distributions).
    rcs="$HOME/.profile"
    [ "$os" = "Darwin" ] && rcs="$HOME/.profile $HOME/.zprofile"
    for rc in $rcs; do
        grep -qs 'HOME/.local/bin' "$rc" || printf '\nexport PATH="$HOME/.local/bin:$PATH"   # CrossPad\n' >> "$rc"
    done
fi
ok "$(ls "$bin" | tr '\n' ' ')— from any new terminal"
# FL Studio on a Mac reads controller scripts from ~/Documents/Image-Line; the
# DAW Control script goes there, so FL finds the board by itself.
fl_hw="$HOME/Documents/Image-Line/FL Studio/Settings/Hardware"
fl_script="$CROSSPAD_DIR/components/crosspad-dawcontrol/host/fl_studio"
if [ "$os" = "Darwin" ] && { [ -d "$fl_hw" ] || ls -d /Applications/FL\ Studio*.app >/dev/null 2>&1; } \
        && [ -f "$fl_script/device_CrossPad.py" ]; then
    mkdir -p "$fl_hw/CrossPad" && cp -R "$fl_script/." "$fl_hw/CrossPad/" \
        && ok "FL Studio's CrossPad script — FL picks the board up on its next start"
fi

# ---------------------------------------------------------------------------
step "Final check" "in a new terminal, the way you will use it"
for t in git python3 gh code node npx $(ls "$bin"); do
    case "$t" in
        code) [ -n "${CROSSPAD_NO_VSCODE:-}" ] && continue ;;
        node|npx) [ -n "${CROSSPAD_NO_MCP:-}" ] && continue ;;
    esac
    if bash -lc "command -v $t" >/dev/null 2>&1; then ok "$t is on PATH"
    else bad "$t is not on PATH in a new terminal" "open a new terminal and run this installer again"; fi
done
if bash -lc "export IDF_TOOLS_PATH='$IDF_TOOLS'; . '$IDF_DIR/export.sh' >/dev/null 2>&1 && idf.py --version" >/dev/null 2>&1; then
    ok "idf.py works inside cptools"
else
    bad "idf.py does not start" "run this installer again"
fi
# The doctor's view of the whole setup. A board that is not plugged in yet is
# not an installation problem, so only this script's own steps decide below.
bash -lc 'cptools doctor'

printf '\n'
if [ ${#failed[@]} -eq 0 ]; then
    printf '%sAll set.%s Next time, open a terminal and type:  cptools\n' "$green" "$off"
    printf 'Plug your CrossPad in with a USB cable before [1] Update my CrossPad.\n'
else
    printf '%sAlmost:%s the lines marked ✗ above say what is left.\n' "$yellow" "$off"
    printf 'Run this installer again after fixing them — it only redoes what is missing.\n'
fi
if [ -z "${CROSSPAD_NO_TUI:-}" ] && [ -t 1 ] && [ -e /dev/tty ]; then
    printf '\nOpening CP Tools…\n'
    exec "$bin/cptools" </dev/tty
fi
