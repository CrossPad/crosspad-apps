# CrossPad developer setup — instructions for an AI assistant

You are an AI coding assistant. A developer pasted a short message asking you
to set up CrossPad development on their computer by following this file. Do
it end to end, step by step, and check each step before the next one. This
file is kept current with the CrossPad repositories; when it and something
older you know disagree, this file wins.

**Talk to the developer in the language their message was written in** (this
file is in English; your questions, summaries and the Step 7 hand-over are in
their language). Commands, file names and on-screen labels stay as they are.

**Goal.** At the end, on the developer's computer:

1. the toolchain is installed (ESP-IDF 5.5, git, Python, the CrossPad commands),
2. the firmware project `CrossPad/platform-idf` is cloned with all its submodules,
3. the firmware is built for the developer's board (`build_v2/CrossPad.bin`),
4. the flash commands are ready, and you have **stopped** before flashing and
   handed over to the developer (Step 7).

Human-oriented documentation for every step is on https://crosspad.app/docs/
([Start here](https://crosspad.app/docs/start-here/),
[CLI reference](https://crosspad.app/docs/reference/cli/),
[Troubleshooting](https://crosspad.app/docs/troubleshooting/)). Open it when a
step here fails in a way this file does not cover.

## Rules for you

- **Ask the developer as little as possible.** Detect the OS, the shell, what is
  already installed. The only things you ask for are listed below.
- **Stop and ask the developer** before:
  - anything that needs their password (`sudo`, a macOS or Windows admin prompt) —
    never type, guess or store a password; give them the one command to run in
    their own terminal instead;
  - signing in anywhere (GitHub, npm) or using any token or credential;
  - **anything that writes to their CrossPad board** — flashing firmware or assets,
    switching its USB mode. The first flash always needs them in front of the
    board (it asks them to press buttons).
- Run commands that take longer than your shell tool allows (the installer and
  the first build take 15–40 minutes each) **in the background, writing to a log
  file**, then check the log every few minutes. Do not start a second copy while
  one is running.
- Do not edit the project's tracked files to make a step pass (no changes to
  `sdkconfig.*`, `CMakeLists.txt`, submodules). If a step fails, find the cause.
- After each step, tell the developer in one line what you did and what you saw.
- **Board testing tools (crosspad-hil, `tools/bench.py test`, smoke tests) are
  not publicly available yet.** Skip every step that needs them, here and on
  the docs site. The setup is complete without them.

## Step 0 — Look at the computer

Find out, without asking:

| What | How (Linux/macOS) | How (Windows, PowerShell) |
|---|---|---|
| OS and version | `uname -s; cat /etc/os-release 2>/dev/null; sw_vers 2>/dev/null` | `[Environment]::OSVersion` |
| CPU | `uname -m` | `$env:PROCESSOR_ARCHITECTURE` |
| Free disk in the home folder (need **≥ 10 GB**) | `df -h ~` | `Get-PSDrive C` |
| User name | `id -un` | `$env:USERNAME` |
| Passwordless sudo (Linux) | `sudo -n true 2>/dev/null && echo yes || echo no` | — |
| Existing setup | `ls -d ~/CrossPad ~/esp/esp-idf* 2>/dev/null` | `Test-Path C:\CrossPad\firmware` |

- An existing `~/CrossPad` (Windows `C:\CrossPad\firmware`) is fine: the
  installer only fills in what is missing and never overwrites the developer's
  own changes. Do not delete it.
- An ESP-IDF 5.5.4 or newer 5.5.x that is already installed is found and used.
  An older 5.5, or another major version, is left alone and 5.5.5 is installed
  next to it. ESP-IDF 6.x is not supported.
- Paths must not contain spaces or non-ASCII letters (ESP-IDF cannot build there).
  If the home folder does, ask the developer for a folder without them and pass
  it as `CROSSPAD_DIR` (Linux/macOS) or `CROSSPAD_ROOT` (Windows) in Step 2.
- Less than 10 GB free: tell the developer and stop. (A finished setup with one
  build takes about 6 GB: ESP-IDF's tools ~4 GB, ESP-IDF ~0.7 GB, the project
  with `build_v2` ~0.9 GB.)

Then go to the section for the OS: [Linux](#step-1-linux--system-packages),
[macOS](#step-1-macos--command-line-tools-and-homebrew),
[Windows](#step-1-windows--nothing-to-prepare).

## Step 1 (Linux) — system packages

The installer needs these packages. Check which are missing:

```bash
for t in git curl python3 cmake ninja wget flex bison gperf dfu-util node npm gh; do command -v $t >/dev/null || echo "missing: $t"; done
python3 -c "import venv, ensurepip" 2>/dev/null || echo "missing: python3-venv"
ldconfig -p 2>/dev/null | grep -q 'libasound\.so\.2' || echo "missing: ALSA library"
python3 -c 'import sys; print("python ok" if sys.version_info >= (3,10) else "python too old")'
id -nG "$(id -un)" | tr ' ' '\n' | grep -qxE 'dialout|uucp' && echo "serial access ok" || echo "missing: serial port group"
```

If nothing is missing, go to Step 2. Otherwise the packages are installed with
`sudo`. If `sudo -n true` succeeded in Step 0 you may run the line for the
distribution yourself; if not, **give the developer the line for their
distribution, ask them to run it in their own terminal (it asks for their
password once) and to tell you when it has finished.** Then run the checks
above again.

Ubuntu / Debian / Mint / Pop!_OS:

```bash
sudo apt-get update && sudo apt-get install -y git curl wget flex bison gperf python3 python3-pip python3-venv cmake ninja-build ccache libffi-dev libssl-dev dfu-util libusb-1.0-0 libasound2-dev nodejs npm gh && sudo usermod -aG dialout "$USER"
```

Fedora:

```bash
sudo dnf install -y git curl wget flex bison gperf python3 python3-pip cmake ninja-build ccache libffi-devel openssl-devel dfu-util libusb1 alsa-lib nodejs npm gh && sudo usermod -aG dialout "$USER"
```

Arch / Manjaro:

```bash
sudo pacman -S --needed --noconfirm git curl wget flex bison gperf python python-pip cmake ninja ccache libffi openssl dfu-util libusb alsa-lib nodejs npm github-cli && sudo usermod -aG uucp "$USER"
```

openSUSE:

```bash
sudo zypper -n install git curl wget flex bison gperf python3 python3-pip cmake ninja ccache libffi-devel libopenssl-devel dfu-util libusb-1_0-0 alsa nodejs npm gh && sudo usermod -aG dialout "$USER"
```

Notes:

- The serial-port group (`dialout`, on Arch `uucp`) takes effect after the
  developer **logs out and back in once**. Tell them; it matters only for
  flashing (Step 7), not for building.
- The ALSA library (`libasound2-dev`, `alsa-lib`, `alsa`) is for the flash tool:
  it talks MIDI to the board to switch its USB mode. Desktop systems have it
  already; minimal and server installs do not.
- `gh` (GitHub CLI) is needed only to publish apps. If the distribution has no
  `gh` package, drop it from the line; the installer then prints one
  `✗ GitHub CLI (gh) is missing` line, which does not stop anything else.
- `node`/`npm` (18 or newer) are for the CrossPad MCP server (Step 2). If the
  distribution's Node.js is older than 18, drop them and add
  `CROSSPAD_NO_MCP=1` in Step 2.

## Step 1 (macOS) — Command Line Tools and Homebrew

```bash
xcode-select -p >/dev/null 2>&1 && echo "CLT ok" || echo "missing: Command Line Tools"
command -v brew >/dev/null && echo "brew ok" || echo "missing: Homebrew"
```

- Command Line Tools missing: run `xcode-select --install`, then **ask the
  developer to click Install in the window that opens** and tell you when it
  has finished.
- Homebrew missing: it needs the developer's password, so **ask them to run this
  in their own Terminal** and tell you when it has finished:

  ```bash
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  ```

Then, in the shell you run Step 2 from, put Homebrew first on the PATH (the
Python that comes with the Command Line Tools is too old, Homebrew's is used):

```bash
eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
```

The installer installs everything else with Homebrew itself (git, cmake, ninja,
dfu-util, python3, gh, node, VS Code), no password needed. Go to Step 2.

## Step 1 (Windows) — nothing to prepare

The Windows installer installs git, Python, ESP-IDF, Node.js and the rest for
the current user with `winget` (built into Windows 10 and 11), no
administrator rights. It puts everything in `C:\CrossPad` (the project in
`C:\CrossPad\firmware`). When winget cannot install a program for the user
alone it installs it for the whole computer, and Windows may show a permission
(UAC) prompt: tell the developer it may appear and that they should accept it.
Go to Step 2.

If your shell is Git Bash or another POSIX shell, run the Windows commands
below through `powershell -NoProfile -Command "…"`.

## Step 2 — Run the CrossPad installer, unattended

The installer is the same one-line installer humans use
([install/README.md](https://github.com/CrossPad/crosspad-apps/blob/main/install/README.md)),
run with options that make it ask nothing and skip what is not available:

| Option | Why |
|---|---|
| `CROSSPAD_YES=1` | answer every question with yes; the PC simulator and Arduino extras stay off |
| `CROSSPAD_NO_HIL=1` | skip the board test tools (not publicly available yet) |
| `CROSSPAD_NO_TUI=1` | do not open the CP Tools menu at the end (it waits for keys) |
| `CROSSPAD_NO_VSCODE=1` | **Linux only, and only if `code` is not installed** (`command -v code`): installing VS Code there needs the developer's password. With VS Code present, leave it out: the installer adds the ESP-IDF extension and points VS Code at the project. On macOS and Windows the installer installs VS Code without a password; leave it out there too |
| `CROSSPAD_WITH_PC=1` | add this only if the developer asked for the PC simulator (Linux also needs `build-essential libsdl2-dev pkg-config`, installed with `sudo` as in Step 1) |

Linux and macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/CrossPad/crosspad-apps/main/install/install.sh -o /tmp/crosspad-install.sh
CROSSPAD_YES=1 CROSSPAD_NO_HIL=1 CROSSPAD_NO_TUI=1 nohup bash /tmp/crosspad-install.sh > ~/crosspad-install.log 2>&1 &
```

(on Linux add `CROSSPAD_NO_VSCODE=1` before `nohup` when VS Code is not installed).

Windows (PowerShell):

```powershell
$env:CROSSPAD_YES="1"; $env:CROSSPAD_NO_HIL="1"; $env:CROSSPAD_NO_TUI="1"
irm https://raw.githubusercontent.com/CrossPad/crosspad-apps/main/install/install.ps1 -OutFile $env:TEMP\crosspad-install.ps1
Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File $env:TEMP\crosspad-install.ps1" -RedirectStandardOutput $HOME\crosspad-install.log -RedirectStandardError $HOME\crosspad-install.err -WindowStyle Hidden
```

**It takes 15–30 minutes** (ESP-IDF is the long part). Check the log every few
minutes (`tail -n 30 ~/crosspad-install.log`, PowerShell
`Get-Content $HOME\crosspad-install.log -Tail 30`). It works through
`Step N of 10`; each step ends with `✓` (Windows `[OK]`) or `✗` (`[X]`) lines.
It has finished when the log shows `All set.` or `Almost:`.

**Success looks like:**

```
Step 4 of 10: ESP-IDF 5.5
  ✓ ESP-IDF v5.5.5 at /home/<user>/esp/esp-idf
…
Step 6 of 10: Test tools (optional)
  skipped
…
Step 10 of 10: Final check
  ✓ idf.py works inside cptools
…
All set. Next time, open a terminal and type:  cptools
```

`cptools doctor` runs at the very end and lists rows such as `Board found` or
`GitHub sign-in` as `[BAD]` or `[ ? ]` while no board is plugged in and nobody is
signed in to GitHub. That is expected now; only the installer's own `✓`/`✗`
lines and the `All set.` / `Almost:` line decide whether this step passed.

If it ends with `Almost:`, read every `✗` line: each one says what to do. Fix
it (see [When something fails](#when-something-fails)) and run the same
command again — the installer only redoes what is missing.

Where things are now:

| | Linux / macOS | Windows |
|---|---|---|
| Project | `~/CrossPad` | `C:\CrossPad\firmware` |
| ESP-IDF | `~/esp/esp-idf` (or the 5.5 that was already there) | `C:\CrossPad\esp-idf` (or the 5.5 that was already there) |
| CrossPad commands | `~/CrossPad/bin/` (linked into `~/.local/bin`) | `C:\CrossPad\firmware\bin\*.cmd` (on the user PATH) |

Your own shell started before the installer, so it may not see the new PATH.
**Call the commands by their full path** from here on:
`~/CrossPad/bin/crosspad-idf` (Windows `C:\CrossPad\firmware\bin\crosspad-idf.cmd`), and so on.
Each of them loads ESP-IDF by itself; you never need `export.sh`. On Windows,
if `git` or `python` is not found in your shell either, reload the PATH the
installer wrote:
`$env:Path = [Environment]::GetEnvironmentVariable('Path','User') + ';' + [Environment]::GetEnvironmentVariable('Path','Machine')`.

## Step 3 — Check the toolchain

```bash
~/CrossPad/bin/crosspad-idf --version
git -C ~/CrossPad submodule status | grep -c '^-' || true
```

Windows: `C:\CrossPad\firmware\bin\crosspad-idf.cmd --version` and
`git -C C:\CrossPad\firmware submodule status`.

**Success:** `ESP-IDF v5.5.x` (x ≥ 4), and `0` submodules starting with `-`
(a `-` means not downloaded). If any are missing:
`git -C ~/CrossPad submodule update --init --recursive`.

## Step 4 — Which board

Every build names the board revision; there is no default build.

```bash
~/CrossPad/bin/crosspad-idf board
```

- It prints a revision and where it came from, e.g. `v2  (device …)` with a
  board plugged in, or `v2  (memory)`. Use that revision.
- It prints `no board revision known — connect a board, or tools/crosspad_board.py --set v2`
  and exits with 2 (no board plugged in, nothing remembered): use **v2**.
  The CrossPads people have are v2 boards (PCB revision 2.0, "r20", printed on
  the circuit board). Only an early prototype with PCB 1.6 or 1.9 is **v1**;
  do not ask unless the developer mentions a prototype.

Remember the choice:

```bash
~/CrossPad/bin/crosspad-idf board --set v2
```

For v1 replace `build_v2`/`sdkconfig.v2` with `build_v1`/`sdkconfig.v1`
everywhere below.

## Step 5 — Build the firmware

```bash
cd ~/CrossPad
nohup ~/CrossPad/bin/crosspad-idf -B build_v2 -DSDKCONFIG=sdkconfig.v2 build > ~/crosspad-build.log 2>&1 &
```

Windows (PowerShell; the quotes around `-D…` are required there):

```powershell
Start-Process C:\CrossPad\firmware\bin\crosspad-idf.cmd -ArgumentList '-B build_v2 "-DSDKCONFIG=sdkconfig.v2" build' -RedirectStandardOutput $HOME\crosspad-build.log -RedirectStandardError $HOME\crosspad-build.err -WindowStyle Hidden
```

The first build compiles ~2000 files and downloads components: from about
**3 minutes** on a 16-core machine to **40 minutes** on a small laptop. Check the log every few minutes.

**Success:** the log ends with `Project build complete. To flash, run:` and
these files exist:

```bash
ls -l ~/CrossPad/build_v2/CrossPad.bin ~/CrossPad/build_v2/assets.bin
```

Never run a bare `idf.py build` (it stops on purpose and names both
revisions), and never edit `sdkconfig.v2` to get past an error.

## Step 6 — Get the flash commands ready (no board needed)

Check that the flash tools start:

```bash
~/CrossPad/bin/crosspad-flash --help
~/CrossPad/bin/crosspad-files --help
```

**Success:** both print a `usage:` text (`crosspad-flash` = `tools/ota_flash.py`,
OTA update over USB; `crosspad-files` = `tools/fs_transfer.py`, files and the
assets partition).

Optional, if the developer uses Claude Code: the installer registered the
CrossPad MCP server (`claude mcp list` shows `crosspad`); other assistants
can use `~/CrossPad/.vscode/mcp.json` (`npx -y crosspad-mcp-server@latest`).

## Step 7 — Stop here and hand over

Tell the developer that the setup is ready and the firmware is built. **Do not
flash on your own.** Give them this summary, adapted to their OS, and wait for
them to say they want to flash now:

> Your CrossPad firmware is built (`~/CrossPad/build_v2/CrossPad.bin`). To put it on
> the board:
>
> 1. Plug the CrossPad in with a USB **data** cable and switch it on. Keep it in
>    front of you. (Linux: log out and back in once first, if you have not since
>    the setup.)
> 2. I run `crosspad-flash`. The board's USB port normally carries MIDI and audio
>    and no serial port, so the tool asks the board to switch: the board shows
>    **USB serial mode?** — press **Allow** within 10 seconds. (Or switch it
>    yourself first: **Settings → USB → Mode → MIDI + Serial**.)
> 3. The board shows the update: press **Update** within 60 seconds.
> 4. When the tool says `Running slot: trial`, **leave the board alone for 10
>    seconds** — the new firmware confirms itself; a reset or unplug before that
>    rolls it back to the old one.
>
> Nothing is lost: the board keeps the firmware it ran before in its second
> slot (see "Getting back" below).

When the developer says go, run (from the project folder):

```bash
~/CrossPad/bin/crosspad-flash
```

and report what it prints. Expected, in order: `Sending USB mode switch
SYSEX`, `CrossPad CDC available on …`, `Waiting for user confirmation on
device...`, `OTA complete!`, `Running slot: trial`. Windows:
`C:\CrossPad\firmware\bin\crosspad-flash.cmd`.

The **assets partition** (app icons, on-board docs, the bundled STM32 image) is
not part of that update. Flash it too when the developer added or changed an
app, or the home screen shows blank icons — again only when they say go:

```bash
~/CrossPad/bin/crosspad-files assets
```

The board restarts once the image is written (no **Update** press). If the
board then offers an **STM32 update** on its screen, the developer presses
**Update** and waits for `Done: STM32 …`.

### Getting back (tell the developer this before the first flash)

- **On the board:** open the **Firmware** app → **Library**, pick the other slot
  (A or B) → **Run** → **Restart**. That boots the firmware it ran before; no
  computer needed. A slot that was rolled back is offered **Try this slot again**.
- **From the computer:** `~/CrossPad/bin/cptools`, press **3** (Something's
  wrong), pick **Previous firmware**, press Enter and confirm.
- **Official firmware back, from a browser:** https://play.crosspad.app/device in
  Chrome or Edge (Web Serial) → **Connect USB & Update** puts the latest
  official release on the board (STM32 first, then the ESP32).
- **Board no longer starts:** reflash everything over the STM32 bridge port
  (USB ID `0483:5740`, always present while the board has power):
  `~/CrossPad/bin/crosspad-idf -B build_v2 -DSDKCONFIG=sdkconfig.v2 -p <port> -b 460800 flash`.
  The port is the one whose USB ID is `0483:5740`: on Linux
  `ls -l /dev/serial/by-id/` (an `…STMicroelectronics…` entry), on macOS
  `ls /dev/cu.usbmodem*`, on Windows the `COM` port of the STMicroelectronics
  Virtual COM Port in Device Manager. Details:
  [Flash or recover over UART](https://crosspad.app/docs/how-to/flash-uart/).
- Official release images: https://github.com/CrossPad/platform-idf/releases
  (`CrossPad-<tag>-v2-<kit>.bin`; `full` is the complete firmware). Flash one
  with `crosspad-flash path/to/CrossPad-<tag>-v2-full.bin --board v2`.

## After the setup: daily work

Tell the developer these in your closing message (short):

- **Build and flash again:** `crosspad-idf -B build_v2 -DSDKCONFIG=sdkconfig.v2 build`, then `crosspad-flash`.
- **Get the latest code:** `cd ~/CrossPad && git pull && git submodule update --init --recursive`,
  then build. Or `cptools` → **1** Update my CrossPad (it also updates the apps and flashes).
- **Add, remove or update apps:** `cptools` → **2**, or `crosspad-idf app-manage`.
  After adding or removing an app, rebuild from clean:
  `crosspad-idf -B build_v2 fullclean`, then build again.
- **Write a new app:** `crosspad-idf app-new --app <id> --name "<Name>"`, then
  `fullclean` + build. Apps live in their own repositories as submodules.
  Guide: https://crosspad.app/docs/how-to/new-app/ — publishing:
  https://crosspad.app/docs/how-to/publish-app/.
- **Contribute to the firmware:** fork `CrossPad/platform-idf` on GitHub, work on a
  branch, open a pull request against `main`. Read `CLAUDE.md` in the project
  first (architecture, rules, gotchas); changes to `components/crosspad-core`,
  `components/crosspad-gui` or an app go to that repository's own pull request.
- **No board yet?** The PC simulator runs the same apps in a window:
  https://crosspad.app/docs/start-here/pc-simulator/ (or run the installer
  again with `CROSSPAD_WITH_PC=1`).
- **Help:** https://crosspad.app/docs/troubleshooting/, and `cptools support`
  writes one file with everything a helper needs (no passwords) for the
  CrossPad Discord, channel #help.

## When something fails

| You see | Cause | Do |
|---|---|---|
| `sudo: a terminal is required to read the password` / `sudo: a password is required` | you ran `sudo` without a password | do not retry; give the developer the Step 1 line to run themselves |
| installer: `✗ Some packages did not install` | Step 1 was skipped or incomplete | do Step 1, run the installer again |
| installer: `USER: unbound variable` | the shell has no `USER` variable | `export USER="$(id -un)"`, run again |
| installer: `✗ Python … is too old` | Python < 3.10 | install a newer `python3` with the package manager (needs the developer, as in Step 1) |
| installer log: `RPC failed`, `early EOF` or `Retry scheduled` while cloning | the network dropped for a moment | nothing, if the step still ends with `✓`: git retries by itself. If it ends with `✗ … download failed`, run the installer again |
| installer: `✗ ESP-IDF did not install` | download cut off, or a broken Python environment | read `/tmp/crosspad-idf-install.log`, run the installer again (it repairs its own ESP-IDF) |
| installer: `✗ your ESP-IDF at … does not start` | an ESP-IDF 5.5 that was already there is broken | run again with `CROSSPAD_IDF_DIR=~/esp/crosspad-idf` for a separate one |
| installer: `✗ GitHub CLI (gh) is missing` | no `gh` | harmless for building; install `gh` later to publish apps |
| installer: `✗ VS Code did not install` | VS Code missing and installing it needs a password | run again with `CROSSPAD_NO_VSCODE=1`; the developer can install VS Code themselves later and run the installer again |
| installer: `✗ the MCP server did not answer` / `✗ Node.js 18 or newer is missing` | Node.js missing or old, or npm cannot reach the registry | harmless for building; or run again with `CROSSPAD_NO_MCP=1` |
| installer: `✗ … is not on PATH in a new terminal` | `~/.local/bin` is not on the login PATH yet | harmless for you (use full paths); the developer opens a new terminal |
| `crosspad-idf: command not found` | your shell predates the installer | use the full path `~/CrossPad/bin/crosspad-idf` |
| build: `FATAL_ERROR` naming `sdkconfig.v1` and `sdkconfig.v2` | `idf.py build` without `-B build_v2 -DSDKCONFIG=sdkconfig.v2` | use the full Step 5 command |
| build: `circular import` around littlefs | `build_v2/littlefs_py_venv` made by another Python | delete `~/CrossPad/build_v2/littlefs_py_venv`, build again |
| build: a component or submodule file not found | a submodule did not download | `git -C ~/CrossPad submodule update --init --recursive`, then `crosspad-idf -B build_v2 fullclean` and build |
| build: `No space left on device` | disk full | tell the developer; delete nothing of theirs |
| flash: `ImportError: libasound.so.2` | the ALSA library is missing (minimal Linux install) | the developer installs `libasound2-dev` (Fedora/Arch `alsa-lib`, openSUSE `alsa`) with `sudo`, as in Step 1 |
| flash: `error creating ALSA sequencer client` | the ALSA MIDI sequencer is not available (no `/dev/snd/seq`: a VM or container without sound, or the `snd-seq` module not loaded) | `sudo modprobe snd-seq` (the developer runs it); in a VM pass the USB device through, or switch the board to serial first (Settings → USB → Mode → MIDI + Serial) so no MIDI is needed |
| flash: `CDC port not found` and no MIDI port | board off, charge-only cable, or (Linux) no access to serial/MIDI devices | ask the developer to check the cable and the power; Linux: log out and in once (`dialout` group) |
| flash: times out waiting for the CDC port | **Allow** not pressed in time, or **Ask before USB serial** prompt missed | ask the developer to switch with Settings → USB → Mode → MIDI + Serial, then run `crosspad-flash` again |
| flash: `expected OTA_READY` / times out waiting for confirmation | **Update** not pressed within 60 s | run again, the developer presses **Update** |
| flash: `the revision of the board on … is unknown` | the tool cannot read the board's revision | run again with `--board v2` |
| board rolled back to the old firmware | it was reset or unplugged within 10 s after the flash | flash again and leave it alone for 10 s |

Anything else: search https://crosspad.app/docs/troubleshooting/ for the exact
message, and tell the developer what you tried. Do not work around a failure
by changing project files.
