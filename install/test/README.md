# Testing the installers

Both installers are tested the way a user meets them: a clean machine, the
install line, then the same machine broken on purpose and the line again.
Neither bench touches the machine it runs on.

## Linux — `linux/run.sh`

```bash
install/test/linux/run.sh        # ~30 minutes, Docker
```

Runs this checkout's `install.sh` in a clean `ubuntu:24.04` as an ordinary
user with sudo (`scenario.sh`):

| Log | What |
|---|---|
| `1-fresh` | nothing installed; PC simulator and Arduino extras on |
| `2-broken` | Python env deleted, a component without its `.git`, ESP-IDF's `tools/` gone |
| `3-existing-idf` | ESP-IDF 5.5 moved to where EIM puts it, with EIM's `esp_idf.json`: found and used, not cloned |
| `4-foreign-idf-dir` | that ESP-IDF named by `CROSSPAD_IDF_DIR`, with an edit and a broken `idf.py`: the edit survives (`4-foreign-edit.txt`) |
| `5-commands` | every command in a login shell, `crosspad-idf board` from `/tmp`, `cptools doctor` |

Pass: `exit=0` in logs 1–4, `# mine` in `4-foreign-edit.txt`, no
`STRAY-BUILD-DIR` in 5. `doctor exit=1` in 5 is the missing board.

## Windows — `windows/wintest.sh`

Windows 11 under KVM in Docker ([dockurr/windows](https://github.com/dockur/windows)),
noVNC on http://127.0.0.1:8006. Disks, ISO and the share live in
`$WINTEST_HOME` (`~/.cache/crosspad-wintest`): ~11 GB for the clean disk, ~16 GB
with FL, up to ~40 GB for the running disk after a full setup with both extras.

```bash
windows/wintest.sh golden        # once: install Windows 11 (downloads the ISO), keep the clean disk
windows/wintest.sh golden-fl     # once: the clean disk + FL Studio (trial)
gh auth token > ~/.cache/crosspad-wintest/shared/token.txt   # every job deletes it at the end
windows/wintest.sh start         # the clean disk again (~1 min), waits for logon
windows/wintest.sh job windows/jobs/run-test.ps1             # fresh + broken, logs in shared/win-*.log
WINTEST_USB=1 windows/wintest.sh start
windows/wintest.sh job windows/jobs/run-board.ps1            # with the real board: update-board
windows/wintest.sh fl            # golden-fl + the board: full setup with both extras, then fl-check.ps1
windows/wintest.sh job windows/jobs/arduino-upload.ps1      # after fl: pio upload on the board, update-board back, smoke
windows/wintest.sh stop          # the board goes back to the host
```

`fl-check.ps1` prints one `PASS`/`FAIL` line per check and `RESULT:` last:
DAW Control on the board, the installer's FL script in place, FL connects,
names and tempo reach the LCD, control mode, transport both ways, disconnect.

Traps, each found the hard way:

- **Nothing through Win+R.** Defender reads a pasted `powershell … -File …`
  in the Run box as ClickFix (Behavior:Win32/SuspClickFix.G2) and kills the
  whole process tree. Jobs go through `jobs/queue.ps1`, which the VM starts at
  every logon and which runs each `shared/job.ps1` it finds.
- **By name, not by listing.** Samba does not tell the Windows client about
  changes made on the host: a directory listing of the share stays stale, a
  lookup by name does not.
- **A sound card in the VM** (`-audiodev none` + `ich9-intel-hda`): without an
  audio endpoint FL's MIDI settings window (F10) hangs FL for good.
- **The board after a restart.** libusb inside the container gets no hotplug
  events; `wintest.sh follow-usb` (started by `WINTEST_USB=1`) re-adds a board
  that came back under a new address through the QEMU monitor.
- **noVNC clicks** open FL's menus only with a pause: move without a button,
  150 ms, down, 120 ms, up.
- `-NoExit` in front of `irm … | iex` is flagged as Trojan:Win32/Commando.A!ml;
  the README's line, without it, passes.

## Windows CI runner — `windows/winrunner.sh`

The same VM, kept running, as a GitHub Actions runner for a private
repository (default `CrossPad/crosspad-hil`), whose hosted Windows minutes are
paid. Public repositories stay on `windows-latest`: free there, and a
self-hosted runner would run a fork's pull request on this machine. Disk and
share in `$WINRUNNER_HOME` (`/mnt/backup/winrunner`), noVNC on
http://127.0.0.1:8007; it runs beside `wintest.sh`.

```bash
windows/winrunner.sh create      # once: the golden disk + Git + the runner as a service (SYSTEM)
windows/winrunner.sh on          # CI_WIN_RUNNER=crosspad-win: jobs come to the VM
windows/winrunner.sh status      # VM, runner online/busy, the variable
windows/winrunner.sh off         # back to windows-latest — before powering the PC down
windows/winrunner.sh job FILE.ps1   # run a script in the VM (after start)
```

The workflow reads `runs-on: ${{ vars.CI_WIN_RUNNER || 'windows-latest' }}`.
The container restarts with Docker, the runner with Windows.

- **The clock.** QEMU gives Windows the host's local time as the RTC; under the
  golden disk's Pacific zone the VM ran 7 h ahead and GitHub refused the
  runner's tokens (`The token is not valid until …`, then a misleading "runner
  registration has been deleted"). `runner-setup.ps1` sets the host's zone
  (`WINRUNNER_TZ`, default Central European) and turns the time service on.
