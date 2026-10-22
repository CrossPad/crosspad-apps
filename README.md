# CrossPad App Registry

Central registry of available CrossPad applications. Auto-discovered from GitHub repos with the `crosspad-app` topic, plus external repos listed in `external-apps.json`.

> **Want to publish your app?** See [How It Works](#how-it-works) for setup instructions.

## Latest Updates

<!-- LATEST_UPDATES_START -->
- **Sampler v0.20.0** — the kit types down the kit browser's left are PERF (was KITS), DRUMS, SLICE, PITCH, SONGS, USER -- six keys, 22 px each. SLICE lists the Slice kits ("engine": "slice", what the Slicer writes): one WAV in regions, one voice. Drums are told by KitInfo::isDrums(). Requires core 2.5.
- **Sampler v0.19.0** — the kit browser in the UX 2000 design -- KITS / DRUMS / PITCH / SONGS / USER down the left, five rows of the list on the right, what the highlighted thing is across the top, LOAD and EDIT below. DRUMS are the factory kits whose kit.json says "category": "drums"; PITCH the instruments saved in Pitch Play (LOAD opens one there) and the pitched kits; SONGS the projects on the card (LOAD opens one, then Arrange); USER the kits made on the board, the Recorder's takes (LOAD slices one in the Slicer) and + NEW KIT. The encoder turns the list and a click loads -- a long press leaves it for the keys; a finger drags it, taps a row, taps it again to load. The highlighted kit is heard once the list stands still, and the pads play and light it, read off the card on a worker of its own. LOAD shows the load's progress, and on the kit already loaded goes to the Sampler. EDIT is the card of the highlighted thing: pads, date, folder; for a kit of one's own its name, author, note and tempo and DELETE, as before. The covers and row thumbnails are gone. The gate is the platform's kit picker (core IKitPicker): Arrange's kit tracks pick their kit there, handed back, not loaded; an app opened for a song's second kit track is not held behind the gate. Requires core 2.2 (instrumentOpenRequest, readKitCopy, IKitPicker) and gui 2.2 (the kit browser's back is the app history).
- **Sampler v0.18.0** — builds on the PC simulator and with MSVC -- every RTOS call (waveform cache and loader, kit-load and kit-convert workers) goes through port/SamplerRtos.hpp, which keeps the board's PSRAM stacks, cores and priorities; the kit-selector gate (kit_gate) for every platform; the kit browser and waveform styles are the sampler's own, gui 2.0 no longer has them; a root deleted before the app's teardown is handled (gui 2.0 calls destroy with none); a waveform sweep that met a queue another thread had filled no longer ends the sweeps, so a kit with more layers than the queue gets them all; builds on core 1.70+/gui 1.28+ and on core/gui 2.x (>=1.70.0,<3.0.0 and >=1.28.0,<3.0.0) for the merge window
- **Sampler v0.17.0** — SPECTRUM, one more click on the waveform after FILE, LIVE and RMS: the live spectrum of what is playing (1024-point FFT, 30 Hz-20 kHz on a log axis, -72..0 dBFS, peak ticks), for the sampler and pitched kits alike; requires crosspad-gui 1.28.0
- **Arrange v0.16.0** — two kit tracks, each playing a kit of its own -- ADD TRACK > SEQ > Kit opens the kit loader (the first kit track's kit is the song's, the one the pads and the Sampler play; the second's is its own, in a second engine beside it), and a kit track's menu opens it again to change it. While two kits are up each plays five voices, the ten the card streams cleanly. ARM, the dot on a seq track's header after S and M, which sit on the number's line now -- all three only show, a touch on the header opens its menu, where they are keys: REC and DUB take onto the armed track, and here the pads play its kit. A kit track without a name shows its kit's. A block with notes of its own MOVEs between the two kit tracks. A track's menu is keys, two a row, as large as a dialog's BOUNCE and CANCEL, so it fits the screen and is easy to touch. FOLLOW is a right arrow, not the word, and the keys after it have most of their width back. Requires core 2.2.
- **Sampler v0.16.0** — a kit loads only as far as its pads play. Each reloaded pad is asked whether the engine can sound it (SamplerAudioCallbacks::padPlayable): a pad the kit gives no sample goes dark, one whose sample did not load dim red, and only a pad that plays takes its colour -- the panel taking the new kit's pads mid-swap no longer paints every pad loaded at once. KIT LOADED counts playable pads of those with a sample; a kit none of whose pads plays is a failed load with the reason on the loader bar (no samples on pads / no sample loaded), current so the pad editor can fill it. The waveform cache is read back with the largest buffer PSRAM has (256 kB down to 16), where a fixed 256 kB malloc failed after a few kit changes and every waveform was computed again off the card under the streamer. Swap log: empty=, failed=, why=.
<!-- LATEST_UPDATES_END -->

## CrossPad Official

<!-- APP_TABLE_START -->
| App | Version | Description | Platforms | Requires | Repo |
|-----|---------|-------------|-----------|----------|------|
| **App Store** | 0.1.1 | Browse, install, and manage CrossPad apps from the registry | pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-appstore](https://github.com/CrossPad/crosspad-appstore) |
| **Arrange** | 0.16.0 | Four audio tracks of bounced clips on a timeline | esp-idf, pc | core >=2.2.0,<3.0.0, gui >=2.0.0,<3.0.0 | [CrossPad/crosspad-arrange](https://github.com/CrossPad/crosspad-arrange) |
| **DAW Control** | 0.4.2 | DAW controller surface: pads to the DAW, LED/text feedback from it (FL Studio, Ableton, REAPER); launches the DAW through the host hub | esp-idf, pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-dawcontrol](https://github.com/CrossPad/crosspad-dawcontrol) |
| **DOOM** | 0.1.0 | DOOM (doomgeneric) on the pads, the encoder and the panel; the one app of the doom firmware kit | pc, esp-idf | core >=2.0.0,<3.0.0, gui >=2.0.0,<3.0.0 | [CrossPad/crosspad-doom](https://github.com/CrossPad/crosspad-doom) |
| **Instructions** | 0.3.0 | Markdown-based instructions and help viewer | esp-idf, arduino, pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-instructions](https://github.com/CrossPad/crosspad-instructions) |
| **Mixer** | 0.15.0 | Audio mixer/router — dynamic IAudioNode channels, multi-output routing | pc, esp-idf | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-mixer](https://github.com/CrossPad/crosspad-mixer) |
| **Pad Mixer** | 0.2.2 | Sixteen faders, one per pad | esp-idf, pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-pad-mixer](https://github.com/CrossPad/crosspad-pad-mixer) |
| **Piano** | 0.1.1 | Synth piano with parameter sliders, presets, octave control | pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-piano](https://github.com/CrossPad/crosspad-piano) |
| **Piano Tiles** | 0.1.0 | Piano Tiles for the pads: tiles fall in four lanes, the pads show what comes, each tile plays the next note of a public-domain tune on a small piano synth; levels speed it up, best scores saved on the card; the one app of the pianotiles firmware kit | pc, esp-idf | core >=2.0.0,<3.0.0, gui >=2.0.0,<3.0.0 | [CrossPad/crosspad-pianotiles](https://github.com/CrossPad/crosspad-pianotiles) |
| **Pitch Play** | 0.10.0 | One sample or many, played chromatically on the pads and from a MIDI keyboard | esp-idf | core >=2.2.0,<3.0.0, gui >=2.0.0,<3.0.0 | [CrossPad/crosspad-pitchplay](https://github.com/CrossPad/crosspad-pitchplay) |
| **Pong** | 0.1.0 | Pong against the CPU over nine levels, or two players: encoder and pads as paddles, the pads light the court, square-wave effects; the one app of the pong firmware kit | pc, esp-idf | core >=2.0.0,<3.0.0, gui >=2.0.0,<3.0.0 | [CrossPad/crosspad-pong](https://github.com/CrossPad/crosspad-pong) |
| **Recorder** | 0.5.2 | Record a sample from the mics, the line-in or the pads, and trim it to a loop | esp-idf, pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-recorder](https://github.com/CrossPad/crosspad-recorder) |
| **Sampler** | 0.20.0 | Sample player with 16 pads, waveform editing, kit management | esp-idf, arduino | core >=2.5.0,<3.0.0, gui >=2.2.0,<3.0.0 | [CrossPad/crosspad-sampler](https://github.com/CrossPad/crosspad-sampler) |
| **Sequencer** | 0.10.0 | Record, loop and erase scenes on the pads | esp-idf, pc | core >=2.2.0,<3.0.0, gui >=2.0.0,<3.0.0 | [CrossPad/crosspad-pattern-seq](https://github.com/CrossPad/crosspad-pattern-seq) |
| **Serial Monitor** | 0.1.1 | UART serial monitor with baud rate selection, auto-scroll, clear | pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-serial-monitor](https://github.com/CrossPad/crosspad-serial-monitor) |
| **Slicer** | 0.4.0 | Chop a loop into slices -- by its hits, into equal parts, or live on the pads -- and save it as a kit | esp-idf, pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-slicer](https://github.com/CrossPad/crosspad-slicer) |
| **Song** | 0.3.0 | Arrange scenes on a timeline | esp-idf, pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-song](https://github.com/CrossPad/crosspad-song) |
| **Synthesizer** | 0.1.0 | Polyphonic synth with 3 oscillators, ADSR, filter, effects | arduino | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-synthesizer](https://github.com/CrossPad/crosspad-synthesizer) |

*18 official app(s)*
<!-- APP_TABLE_END -->

## Top 10 Community Apps

<!-- COMMUNITY_TOP_START -->
*No community apps yet — [add yours!](external-apps.json)*
<!-- COMMUNITY_TOP_END -->

---

## Get started — one command

Open a terminal (Windows: PowerShell) and paste the line for your system. It
installs everything the CrossPad needs, asks for a GitHub sign-in (the
firmware repository is private until the OS opens), and opens **CP Tools**.
It takes 15–30 minutes the first time; run it again any time — it only
installs or repairs what is missing.

**Windows**
```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/CrossPad/crosspad-apps/main/install/install.ps1 | iex"
```

**macOS / Linux**
```bash
curl -fsSL https://raw.githubusercontent.com/CrossPad/crosspad-apps/main/install/install.sh | bash
```

Afterwards: the **CP Tools** shortcut on the Windows desktop, or
`~/CrossPad/cptools` on macOS and Linux.

**Step by step, with screenshots: [install/README.md](install/README.md).**

## Using the App Manager (CP Tools)

The CrossPad App Manager is one shared tool for every platform, with a
**CLI** and an interactive **TUI**. The TUI is built for people who have never
used git: it names tasks, not git operations.

### The screens

The first line always says what to do next — an update waiting, an update
that stopped halfway, a board running firmware for another board revision, a
missing tool. Under it, what each waiting update brings (the apps' own commit
messages).

| Key | Screen | What it does |
|-----|--------|--------------|
| `1` | Update my CrossPad | firmware components → download → build → flash → check, one log; `q` or Ctrl+C stops a step, `r` retries from it. When the project is exactly a published release, the release's image is downloaded instead of compiling |
| `2` | Add or remove apps | type to filter; `Enter` on an app picks what it follows: the latest release, development, or one version. A broken app folder is repaired from here |
| `3` | Something's wrong | every check with its fix: board, firmware, tools, USB, internet, disk, project folder; go back to the versions from before; switch the board to its previous firmware slot; `s` saves a report for support |
| `4` | Developer tools | workspace, device, registry, feature flags, profiles, board revision, raw build & flash, new app, submit an app to the catalog, settings |
| `/` | Find an action | every action by name |
| `?` | Help | the keys of the screen you are on, and what the marks mean |

Mouse: the wheel scrolls, clicking a `[key]` label presses it
(`CROSSPAD_NO_MOUSE=1` turns that off). `NO_COLOR=1` drops colour;
`CROSSPAD_PLAIN=1` (or `tui --plain`) prints plain text for screen readers.

### Apps and the firmware they need

Every app declares the crosspad-core and crosspad-gui it builds against
(`requires` in its `crosspad-app.json`, e.g. `"crosspad-core": "^2.0.0"` or
`">=1.70.0,<3.0.0"`; a comma means *and*). Update my CrossPad updates the
firmware components first, then moves each app only to a version they meet:
the newest release that fits, or the branch it follows once that fits. An app
whose next version needs a newer firmware stays where it is and says so —
`0.18.0 waits for a CrossPad update: needs core ^2.0.0, this project has
1.70.0` — on the dashboard, in `status` and `status --json` (`row.state` is
`waits`, `row.why` the reason). An app that stays on a version is checked out
at it, and app folders the project adds are downloaded; an app with your own
changes or commits is never moved. Before compiling, the build stops on any
app that does not fit the core and gui it would build with, naming the app,
the range and the version; `doctor` lists the same.

### Supported Platforms

| Platform | Status | App install dir | Build system |
|----------|--------|----------------|--------------|
| **ESP-IDF** | Full support: update, build, flash, check, recover | `components/` | `idf.py` |
| **Arduino / PlatformIO** | Apps, build, USB upload | `lib/` | `pio` |
| **PC (simulator)** | Apps and build; "Update" rebuilds the simulator | `src/apps/` | CMake |

### Prerequisites

The installer above sets them up. By hand: **Git**, **Python 3.10+**, and for
ESP-IDF, ESP-IDF 5.5. The GitHub CLI (`gh`, signed in) is needed only to
clone the private platform repository and to publish your own apps —
reading the catalog and updating public apps needs no account.

---

## ESP-IDF

### CLI Commands

```bash
idf.py app-list                              # List compatible apps
idf.py app-install --app sampler             # Install app as git submodule
idf.py app-install --app sampler --ref v1.0  # Install specific version/branch
idf.py app-remove --app sampler              # Remove app submodule
idf.py app-update --all [--force] [--dry-run] # Update installed apps
idf.py app-track --app sampler --mode release|development|version|mine
idf.py app-manage                            # Launch the TUI
python3 tools/app_manager.py doctor          # every check, with its fix (exit 1 if something is wrong)
python3 tools/app_manager.py support         # zip of logs and findings for #support
python3 tools/app_manager.py status --json   # also: list --json, doctor --json, device --json
```

### VSCode Toolbar Buttons

Install the [VsCode Task Buttons](https://marketplace.visualstudio.com/items?itemName=spencerwmiles.vscode-task-buttons) extension. Two buttons appear in the status bar:

| Button | Action |
|--------|--------|
| `$(package) CP Tools` | Opens the full interactive TUI |
| `$(zap) OTA` | One-click OTA flash via USB CDC |

Configuration is in `.vscode/settings.json`:

```json
{
    "VsCodeTaskButtons.tasks": [
        {
            "label": "$(package) CP Tools",
            "task": "CrossPad: CP Tools"
        },
        {
            "label": "$(zap) OTA",
            "task": "CrossPad: OTA Flash"
        }
    ]
}
```

### After Install/Remove

**`idf.py fullclean && idf.py build` is required** after adding or removing apps. CMake's `file(GLOB)` runs at configure time only — plain `idf.py build` won't discover new app directories.

---

## Arduino / PlatformIO

### CLI Commands

```bash
python3 scripts/app_manager.py list                  # List compatible apps
python3 scripts/app_manager.py install sampler        # Install
python3 scripts/app_manager.py remove sampler         # Remove
python3 scripts/app_manager.py update --all           # Update all
python3 scripts/app_manager.py sync                   # Sync manifest
python3 scripts/app_manager.py                        # Launch TUI (no args)
```

### Interactive TUI

Launch with `python3 scripts/app_manager.py` (no arguments) or via the VSCode toolbar button.

The same screens as above; building uses `pio run`, flashing `pio run --target upload`.

### VSCode Toolbar Button

Same setup as ESP-IDF — install [VsCode Task Buttons](https://marketplace.visualstudio.com/items?itemName=spencerwmiles.vscode-task-buttons), then configure in `.vscode/settings.json`:

```json
{
    "VsCodeTaskButtons.tasks": [
        {
            "label": "$(package) CP Tools",
            "task": "CrossPad: App Manager"
        }
    ]
}
```

### After Install/Remove

```bash
pio run --target clean && pio run
```

---

## Creating a New App

Easiest from the TUI — `[N] New app` on the dashboard. It is a form: fill the
id, name and description, cycle **Publish** with space between *local only*,
*private GitHub repo* and *public GitHub repo*, and the panel below previews
exactly what will be created — the directory, the two sources you are meant to
rewrite, the `REGISTER_APP_PL` line, and the repo slug if publishing. Creation
shows each step as it happens and ends on the build command, with `[b]` to run
it right there.

The same thing from the shell:

```bash
python3 <wrapper> new fishtank --name "Fish Tank" --private
```

Generates a complete, working app from [`template/`](template/) and installs it
into the project: a pad handler, LVGL buttons and a slider, an animation timer,
and `REGISTER_APP_PL` registration, so it shows up in the launcher after one
clean build. Then rewrite the two source files — that is the point of it.

| Flag | Effect |
|------|--------|
| *(none)* | Stays local: a plain directory in this project, tracked as `local` |
| `--private` | Creates a private GitHub repo under your account, pushes, installs it back as a submodule |
| `--public` | Same, public |
| `--owner` | Publish under an org instead of your account |
| `--no-install` | Generate only, leave the project alone |

Publishing needs `gh auth login`. A private repo is a fine place to start — the
registry only lists apps you deliberately add to `external-apps.json`.

The template deliberately shows the one rule that is easy to get wrong: pad
callbacks arrive on the pad thread, LVGL is not thread-safe, so the pad handler
only records events and the LVGL timer draws them.


## Workspace, Config and Profiles

The manager treats installed apps as **owned**, not as registry property, and
doubles as the project's compile-time config tool.

### Intent vs state

| File | Written by | Checked in | Holds |
|------|-----------|-----------|-------|
| `apps.json` | manager | yes | State: what is on disk |
| `crosspad.config.json` | you / TUI | yes | Intent: track policy per app, feature flags |
| `crosspad.local.json` | you / TUI | no | Personal overrides (own branches, dev flags) |
| `config/profiles/*.json` | you | yes | Named recipes: flags + app set |
| `.crosspad/` | manager | no | Backups, generated build flags |

### Track policy

```bash
python3 <wrapper> track sampler local              # hands off, this one is mine
python3 <wrapper> track mixer branch --ref my-work # follow my branch, ff-only
python3 <wrapper> track piano pinned               # freeze at the current commit
python3 <wrapper> status                           # policy vs actual git state
```

| mode (screen word) | `update` does |
|------|---------------|
| `registry` (release, default) | follows the newest `v*` release tag |
| `branch` (development) | follows the named branch; never switches branch |
| `pinned` (version) | nothing; reports when newer exists |
| `local` (mine) | nothing at all; the worktree is yours |

The CLI takes either word. Settings → Early features switches every app on
the latest release to development (and back) in your personal config.

The declared mode is intent. Observed git state overrides it: an app that is
dirty, ahead of origin, on an unexpected branch, or pointing at a fork is
blocked whatever its mode. `update --all` updates the clean apps and prints a
skip table for the rest; `--force` proceeds but snapshots first.

### Backups

```bash
python3 <wrapper> backup sampler          # snapshot local work
python3 <wrapper> restore sampler --list  # what is available
python3 <wrapper> restore sampler         # replay the newest
```

A backup lands in `.crosspad/backups/<app>/<ts>/` and holds tracked changes as a
patch, untracked files as a tarball, commits that exist nowhere on origin as a
git bundle, and every stash as its own patch. Restore replays patches and files
in place and fetches the bundle into `refs/crosspad-backup/<ts>/*` — rebuilding
history stays your call. `remove` always backs up first when local work exists.

### Compile-time features

Flags come from `crosspad-core/include/crosspad/config/features.schema.json`,
the machine-readable twin of the Marlin-style `Configuration.h`.

```bash
python3 <wrapper> config                              # show flags, * = overridden
python3 <wrapper> config FEAT_PAD_EDITOR off          # set one
python3 <wrapper> config --gen                        # regenerate build flags
```

Chosen values live in `crosspad.config.json`, never in the submodule header, so
configuring a build does not dirty `crosspad-core` for everyone else. Only
deviations from the header default are emitted, into
`.crosspad/build_flags.cmake` (ESP-IDF, PC — `include()`d by the top-level
`CMakeLists.txt`) and `.crosspad/build_flags.ini` (PlatformIO, applied by a
`pre:` extra script). An untouched project builds exactly as the headers say.

The TUI screen `[C] Configure` renders the same catalog as a menuconfig tree
with help text and `requires` validation.

### Device telemetry

```bash
python3 <wrapper> device        # exits 2 when the device differs
```

Every build bakes in the submodules it was made of — component, registry id,
commit, manifest pin, dirty flag — and reports them in the same `APPVER:` format
on all three platforms:

| Platform | How it answers |
|----------|----------------|
| ESP-IDF | `APP_VERSIONS` over CDC |
| Arduino | `APP_VERSIONS` on the serial console |
| PC | `./bin/CrossPad --versions` |

The manager diffs that against the checkout, so "is this actually running my
code?" stops being guesswork. Same view on the TUI's `[D] Device` screen. A
board in USB audio mode exposes no CDC — switch it back with the SysEx
`F0 7D 1B 00 F7` on its own MIDI port. An app kept in-tree rather than as a
submodule reports `ref=in-tree`, because its commit is the parent repo's.

### Profiles

```bash
python3 <wrapper> profile list
python3 <wrapper> profile show lite       # dry-run diff against the project
python3 <wrapper> profile apply lite
```

A profile is a recipe — feature flags plus the app set with track modes. Apply
shows the plan first; apps the profile omits are kept unless you pass
`--remove-extra`, and apps that are protected or carry local work are never
removed.

---

## PC (simulator)

```bash
python3 scripts/app_manager.py            # TUI
python3 scripts/app_manager.py list       # and every other command above
```

Apps go to `src/apps/`. "Update my CrossPad" updates the apps and rebuilds
the simulator; Developer tools → OTA Flash runs it.

---

## How It Works

1. Each app repo has the GitHub topic `crosspad-app` and contains a `crosspad-app.json` with metadata
2. CI runs `build_registry.py` every 6 hours which:
   - Discovers all repos with the `crosspad-app` topic in the CrossPad org
   - Merges in any external repos from `external-apps.json`
   - Generates `registry.json` + updates this README
   - Sends Discord notifications for new apps, platform additions, and version updates
3. The result is `registry.json` — fetched by the app manager (cached locally for 1 hour)
4. Apps are installed as **git submodules** into the platform's library directory
5. The build system auto-discovers installed components at configure time

### Architecture

```
crosspad-apps/                    ← This repo (registry + shared core)
  registry.json                   ← Auto-generated, consumed by app manager
  crosspad_app_manager.py         ← Shared core (downloaded by platform wrappers)
  build_registry.py               ← CI: discovers repos, builds registry
  diff_registry.py                ← CI: detects changes for Discord notifications

platform-idf/                     ← ESP-IDF platform repo
  idf_ext.py                      ← Registers idf.py app-* commands
  tools/app_manager.py            ← Thin wrapper, auto-downloads shared core
  apps.json                       ← Local manifest of installed apps

ESP32-S3/                         ← Arduino platform repo
  scripts/app_manager.py          ← Thin wrapper, auto-downloads shared core
  apps.json                       ← Local manifest of installed apps
```

## Adding a CrossPad Org App

1. Add `crosspad-app.json` to your app repository:
   ```json
   {
     "name": "My App",
     "id": "my-app",
     "version": "0.1.0",
     "description": "What it does",
     "category": "music",
     "icon": "my-icon.png",
     "component_path": "components/crosspad-my-app",
     "platforms": ["esp-idf", "arduino"],
     "requires": {
       "crosspad-core": ">=0.3.0",
       "crosspad-gui": ">=0.2.0"
     },
     "changelog": [
       "0.1.0: Initial release"
     ]
   }
   ```

2. Add the `crosspad-app` topic to your repo:
   ```bash
   gh repo edit CrossPad/crosspad-my-app --add-topic crosspad-app
   ```

3. CI will auto-discover your app on next run (every 6h), or trigger manually.

## Adding an External (Community) App

From CP Tools: Developer tools → **Submit an app to the catalog** checks your
`crosspad-app.json` and repository and opens the pull request for you.

By hand — for repos outside the CrossPad org, open a PR adding your repo to `external-apps.json`:

```json
{
  "repo": "your-user/your-crosspad-app",
  "url": "https://github.com/your-user/your-crosspad-app.git",
  "branch": "main"
}
```

Your repo must also contain a `crosspad-app.json` with valid metadata.

## Files

| File | Purpose |
|------|---------|
| `registry.json` | Auto-generated registry (consumed by app manager) |
| `crosspad.config.json` | (in each project) Track policy + feature flags — intent |
| `config/profiles/*.json` | (in each project) Named build recipes |
| `crosspad_app_manager.py` | Shared core — all app management + TUI logic |
| `install/install.sh`, `install/install.ps1` | One-command setup for macOS/Linux and Windows |
| `tests/` | Tests of the core, run on Windows, macOS and Linux by CI |
| `build_registry.py` | CI: discovers repos by topic, builds registry |
| `diff_registry.py` | CI: compares registries, outputs changes for notifications |
| `external-apps.json` | Community/third-party app repos (add via PR) |
| `COMMUNITY_APPS.md` | Auto-generated full list of community apps |
## License

GPL-3.0-or-later — see [LICENSE](LICENSE).
