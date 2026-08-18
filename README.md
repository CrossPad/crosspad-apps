# CrossPad App Registry

Central registry of available CrossPad applications. Auto-discovered from GitHub repos with the `crosspad-app` topic, plus external repos listed in `external-apps.json`.

> **Want to publish your app?** See [How It Works](#how-it-works) for setup instructions.

## Latest Updates

<!-- LATEST_UPDATES_START -->
- **Instructions v0.2.0** — Cross-platform support — ESP-IDF, Arduino, PC
- **Mixer v0.2.0** — Dynamic IAudioNode-based channels (up to 16 × 8 outputs); ESP-IDF build target
- **Sequencer v0.2.0** — Pad logic refactor, portable UI components
- **Sampler v0.2.0** — Wire SamplerPadLogic, EventBus audio bridge, kit load task, end=0 normalization
- **Instructions v0.1.0** — Initial release — markdown rendering, file auto-discovery
- **Serial Monitor v0.1.0** — Initial release — live UART output, input field, baud config
<!-- LATEST_UPDATES_END -->

## CrossPad Official

<!-- APP_TABLE_START -->
| App | Version | Description | Platforms | Requires | Repo |
|-----|---------|-------------|-----------|----------|------|
| **App Store** | 0.1.0 | Browse, install, and manage CrossPad apps from the registry | pc | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-appstore](https://github.com/CrossPad/crosspad-appstore) |
| **Instructions** | 0.2.0 | Markdown-based instructions and help viewer | esp-idf, arduino, pc | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-instructions](https://github.com/CrossPad/crosspad-instructions) |
| **Mixer** | 0.2.0 | Audio mixer/router — dynamic IAudioNode channels, multi-output routing | pc, esp-idf | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-mixer](https://github.com/CrossPad/crosspad-mixer) |
| **Piano** | 0.1.0 | Synth piano with parameter sliders, presets, octave control | pc | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-piano](https://github.com/CrossPad/crosspad-piano) |
| **Sampler** | 0.2.0 | Sample player with 16 pads, waveform editing, kit management | esp-idf, arduino | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-sampler](https://github.com/CrossPad/crosspad-sampler) |
| **Sequencer** | 0.2.0 | MIDI step sequencer with recording, playback, overdub | arduino | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-sequencer](https://github.com/CrossPad/crosspad-sequencer) |
| **Serial Monitor** | 0.1.0 | UART serial monitor with baud rate selection, auto-scroll, clear | pc | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-serial-monitor](https://github.com/CrossPad/crosspad-serial-monitor) |
| **Synthesizer** | 0.1.0 | Polyphonic synth with 3 oscillators, ADSR, filter, effects | arduino | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-synthesizer](https://github.com/CrossPad/crosspad-synthesizer) |

*8 official app(s)*
<!-- APP_TABLE_END -->

## Top 10 Community Apps

<!-- COMMUNITY_TOP_START -->
*No community apps yet — [add yours!](external-apps.json)*
<!-- COMMUNITY_TOP_END -->

---

## Using the App Manager

The CrossPad App Manager is a shared tool that works across all platforms. It provides both a **CLI** and an **interactive TUI** for managing apps — browsing, installing, removing, updating, building, and flashing.

### Supported Platforms

| Platform | Status | App install dir | Build system |
|----------|--------|----------------|--------------|
| **ESP-IDF** | Full support | `components/` | `idf.py` |
| **Arduino / PlatformIO** | Full support | `lib/` | `pio` |
| **PC (Desktop)** | Coming soon | `components/` | CMake |

### Prerequisites

- **`gh` CLI** installed and authenticated (`gh auth login`)
- **Git** (apps are installed as git submodules)
- **Python 3.9+**

---

## ESP-IDF

### CLI Commands

```bash
idf.py app-list                              # List compatible apps
idf.py app-list --all                        # Include incompatible platform apps
idf.py app-install --app sampler             # Install app as git submodule
idf.py app-install --app sampler --ref v1.0  # Install specific version/branch
idf.py app-install --app sampler --force     # Install despite platform incompatibility
idf.py app-remove --app sampler              # Remove app submodule
idf.py app-update --app sampler              # Update to latest
idf.py app-update --all                      # Update all installed apps
idf.py app-sync                              # Sync manifest with existing submodules
idf.py app-manage                            # Launch interactive TUI
```

### Interactive TUI

Launch with `idf.py app-manage` or via the VSCode toolbar button.

![TUI Dashboard](docs/tui-dashboard.png)

**Dashboard** — project overview with installed apps, quick actions via hotkeys:
- `[B]` Browse & Install — categorized app browser with `/` search
- `[U]` Update All — update all installed apps
- `[H]` Health Check — submodule status, manifest sync, gh auth, cache age
- `[F]` Build & Flash — idf.py build/flash/monitor with auto-detected serial port
- `[O]` OTA Flash — one-click OTA with build state awareness (detects stale builds)
- `[T]` Dev Tools — force refresh registry, view raw data, clear cache
- `[Q]` Quit

**App Browser** features:
- Categorized view (music, audio, tools)
- Live search with `/` key
- Color-coded status: green = installed, gray = available, red = incompatible
- `Enter` for app details, `i` to install, `r` to remove

**App Detail** shows description, platforms, dependencies, disk usage, recent git commits, changelog (fetched from GitHub), with direct actions (install/remove/update/open repo).

**OTA Flash** checks build state before flashing:
- Shows binary size, build age
- Warns if sources have been modified since last build
- `[Enter]` Flash, `[B]` Build first, `[R]` Build + Flash combo

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

Same features as ESP-IDF TUI — dashboard, browser, detail view, build & flash (using `pio` commands), OTA, health check, dev tools.

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

| mode | `update` does |
|------|---------------|
| `registry` (default) | follows the registry ref, fast-forward only |
| `branch` | follows the named branch; never switches branch |
| `pinned` | nothing; reports when newer exists |
| `local` | nothing at all; the worktree is yours |

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

## PC (Desktop) — Coming Soon

Desktop platform support is planned. The app manager core (`crosspad_app_manager.py`) already supports a `pc` platform config. Stay tuned.

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

For repos outside the CrossPad org, open a PR adding your repo to `external-apps.json`:

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
| `build_registry.py` | CI: discovers repos by topic, builds registry |
| `diff_registry.py` | CI: compares registries, outputs changes for notifications |
| `external-apps.json` | Community/third-party app repos (add via PR) |
| `COMMUNITY_APPS.md` | Auto-generated full list of community apps |