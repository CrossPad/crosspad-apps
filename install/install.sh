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
#   CROSSPAD_IDF_DIR=~/esp/esp-idf where ESP-IDF goes
#   CROSSPAD_YES=1                 answer yes to every question
#   CROSSPAD_NO_HIL=1 / CROSSPAD_NO_MCP=1 / CROSSPAD_NO_TUI=1   skip those parts

set -u

CROSSPAD_DIR="${CROSSPAD_DIR:-$HOME/CrossPad}"
CROSSPAD_BRANCH="${CROSSPAD_BRANCH:-crosspad_v20}"
CROSSPAD_REPO="CrossPad/platform-idf"
IDF_DIR="${CROSSPAD_IDF_DIR:-$HOME/esp/esp-idf}"
IDF_VERSION="v5.5.5"          # what CI builds with
IDF_TARGET="esp32s3"

STEPS=8
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
    if [ -z "$(git -C "$CROSSPAD_DIR" status --porcelain --ignore-submodules)" ]; then
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
step "ESP-IDF $IDF_VERSION" "the compiler for the CrossPad's chip — about 10 minutes the first time"
idf_ok() { ( . "$IDF_DIR/export.sh" >/dev/null 2>&1 && idf.py --version >/dev/null 2>&1 ); }
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
fi
have_ver="$(git -C "$IDF_DIR" describe --tags 2>/dev/null)"
case "$have_ver" in
    v5.5*) ;;
    *) note "found ESP-IDF $have_ver; CrossPad needs 5.5 — using $IDF_VERSION"
       git -C "$IDF_DIR" fetch --quiet --depth 1 origin tag "$IDF_VERSION" \
         && git -C "$IDF_DIR" checkout --quiet "$IDF_VERSION" \
         && git -C "$IDF_DIR" submodule update --quiet --init --recursive --depth 1 ;;
esac
if ! idf_ok; then
    # Deleted or edited files inside ESP-IDF come back from its own git first.
    git -C "$IDF_DIR" checkout --quiet -- . 2>/dev/null
    git -C "$IDF_DIR" submodule update --quiet --init --recursive --depth 1 2>/dev/null
    "$IDF_DIR/install.sh" "$IDF_TARGET" >/tmp/crosspad-idf-install.log 2>&1
    if ! idf_ok; then
        # A broken Python environment is the usual culprit; build it again.
        rm -rf "$HOME/.espressif/python_env/idf5.5_"*
        "$IDF_DIR/install.sh" "$IDF_TARGET" >>/tmp/crosspad-idf-install.log 2>&1
    fi
fi
if idf_ok; then ok "ESP-IDF $(git -C "$IDF_DIR" describe --tags 2>/dev/null)"
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
        ok "crosspad-hil"
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
step "AI assistant tools (optional)" "the CrossPad MCP server, for Claude Code"
if [ -n "${CROSSPAD_NO_MCP:-}" ]; then
    note "skipped"
elif have claude && have npx; then
    if claude mcp get crosspad >/dev/null 2>&1; then
        ok "Claude Code already knows the CrossPad tools"
    elif claude mcp add --scope user crosspad -- npx -y crosspad-mcp-server >/dev/null 2>&1; then
        ok "added to Claude Code"
    else
        note "could not add it — run: claude mcp add crosspad -- npx -y crosspad-mcp-server"
    fi
else
    note "Claude Code or Node.js is not installed — nothing to set up (add later: claude mcp add crosspad -- npx -y crosspad-mcp-server)"
fi

# ---------------------------------------------------------------------------
step "CP Tools" "a launcher, then a check of everything"
launcher="$CROSSPAD_DIR/cptools"
cat > "$launcher" <<EOF
#!/usr/bin/env bash
# CP Tools launcher, written by the CrossPad installer. Run: $launcher [doctor|support|tui]
cd "$CROSSPAD_DIR" || exit 1
. "$IDF_DIR/export.sh" >/dev/null 2>&1
exec python3 tools/app_manager.py "\${@:-tui}"
EOF
chmod +x "$launcher"
python3 - "$CROSSPAD_DIR/crosspad.local.json" "$IDF_DIR" <<'EOF'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
try:
    cfg = json.loads(p.read_text())
except (OSError, ValueError):
    cfg = {}
cfg["idf_path"] = sys.argv[2]
p.write_text(json.dumps(cfg, indent=2) + "\n")
EOF
ok "launcher: $launcher"
# The doctor's view of the whole setup. A board that is not plugged in yet is
# not an installation problem, so only this script's own steps decide below.
"$launcher" doctor

printf '\n'
if [ ${#failed[@]} -eq 0 ]; then
    printf '%sAll set.%s Next time, open CP Tools with:  %s\n' "$green" "$off" "$launcher"
    printf 'Plug your CrossPad in with a USB cable before [1] Update my CrossPad.\n'
else
    printf '%sAlmost:%s the lines marked ✗ above say what is left.\n' "$yellow" "$off"
    printf 'Run this installer again after fixing them — it only redoes what is missing.\n'
fi
if [ -z "${CROSSPAD_NO_TUI:-}" ] && [ -t 1 ] && [ -e /dev/tty ]; then
    printf '\nOpening CP Tools…\n'
    exec "$launcher" tui </dev/tty
fi
