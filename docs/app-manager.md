# CP Tools: details the docs site does not cover yet

The user guide for CP Tools (the app manager in `crosspad_app_manager.py`) is on
the docs site:

- [Install and remove apps](https://crosspad.app/docs/how-to/install-apps/)
- [Create a new app](https://crosspad.app/docs/how-to/new-app/) and [Publish an app](https://crosspad.app/docs/how-to/publish-app/)
- [Command-line tools](https://crosspad.app/docs/reference/cli/): every `cptools` / `tools/app_manager.py` command and every `idf.py app-*` action
- [App manager](https://crosspad.app/docs/subsystems/app-manager/): the screens, workspace policy, feature flags, the device check
- [Troubleshooting → Apps](https://crosspad.app/docs/troubleshooting/#apps)

This page keeps what has no page on the site yet. When the site gains a page
for a section, the section moves there and this page links to it.

In the commands, `<wrapper>` stands for the platform's copy of the manager:
`python3 tools/app_manager.py` in platform-idf (or `cptools` after the one-line
installer), `python3 scripts/app_manager.py` in the PC simulator or the Arduino
firmware. On Windows use `python` for `python3`.

## Platforms

| Platform | Manager | Apps go to | Build | What CP Tools does |
|---|---|---|---|---|
| ESP-IDF (platform-idf) | `tools/app_manager.py`, `idf.py app-*` | `components/` | `idf.py -B build_<rev> -DSDKCONFIG=sdkconfig.<rev>` | Update, build, flash, check, recover |
| PC simulator (crosspad-pc) | `scripts/app_manager.py` | `src/apps/` | CMake | Apps and build. **Update my CrossPad** updates the apps and rebuilds the simulator; Developer tools → **OTA Flash** runs the simulator |
| Arduino / PlatformIO ([legacy](https://crosspad.app/docs/legacy/esp32-s3-arduino/)) | `scripts/app_manager.py` | `lib/` | `pio run` | Apps, build, USB upload (`pio run --target upload`) |

After adding or removing an app, configure from scratch, because the build finds
app folders only then:

- ESP-IDF: `idf.py -B build_v2 fullclean`, then `idf.py -B build_v2 -DSDKCONFIG=sdkconfig.v2 build` (`build_v1` / `sdkconfig.v1` for a v1 board).
- PC: delete `build/`, then `cmake -B build -G Ninja && cmake --build build`.
- Arduino: `pio run --target clean && pio run`.

## Screen options

| Variable | Effect |
|---|---|
| `NO_COLOR=1` | No colour |
| `CROSSPAD_PLAIN=1` (or `tui --plain`) | Plain text, one screen after another, for screen readers |
| `CROSSPAD_NO_MOUSE=1` | Mouse off, so the terminal's own text selection works without Shift |

The mouse (wheel scrolls, a click on a `[key]` label presses it) works in
Linux and macOS terminals only. On Windows it is always off.

In **Update my CrossPad**, `q` or Ctrl+C stops a step, and after a failure `r`
retries from the step that failed.

**[4] Developer tools** holds: Workspace, Device, Browse registry, Configure,
Board (ESP-IDF only), Profiles, **Build & Flash** (the raw `idf.py` / `cmake`
commands), OTA Flash, New app, Registry tools, **Submit an app to the catalog**
and Settings. `/` finds any of them by name.

## Workspace: intent and state

| File | Written by | In git | Holds |
|---|---|---|---|
| `apps.json` | manager | not in platform-idf (`.gitignore`); tracked in crosspad-pc | State: what is on disk |
| `crosspad.config.json` | you / TUI | yes | Intent: what each app follows, feature flags |
| `crosspad.local.json` | you / TUI | no | Personal overrides (own branches, dev flags), CP Tools settings, `idf_path` |
| `config/profiles/*.json` | you | yes | Named recipes: flags plus an app set |
| `.crosspad/` | manager | no | Backups, generated build flags, update logs |

## What an app follows

```bash
<wrapper> track sampler mine                       # hands off, this one is mine
<wrapper> track mixer development --ref my-work    # follow my branch, fast-forward only
<wrapper> track piano version                      # freeze at the current commit
<wrapper> status                                   # policy vs actual git state
```

| Mode (old name) | `update` does |
|---|---|
| `release` (`registry`, the default) | Follows the newest `v*` release tag |
| `development` (`branch`) | Follows the named branch; never switches branch |
| `version` (`pinned`) | Nothing; reports when a newer one exists |
| `mine` (`local`) | Nothing at all; the worktree is yours |

The CLI takes either name. Developer tools → Settings → **Early features** moves
every app that follows the latest release to development (and back), in your
personal config.

The mode is intent; the git state overrides it. An app that has uncommitted
work, is ahead of origin, is on an unexpected branch or points at a fork is
skipped whatever its mode. `update --all` updates the clean apps and prints a
table of the skipped ones; `--force` goes ahead but takes a backup first.

## Apps and the firmware they need

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

## Backups

```bash
<wrapper> backup sampler          # snapshot local work
<wrapper> restore sampler --list  # what is there
<wrapper> restore sampler         # replay the newest
```

A backup lands in `.crosspad/backups/<app>/<timestamp>/`: tracked changes as a
patch, untracked files as a tarball, commits that exist nowhere on origin as a
git bundle, and every stash as its own patch. `restore` replays the patches and
files in place and fetches the bundle into `refs/crosspad-backup/<timestamp>/*`;
rebuilding history from there is up to you. `remove` always takes a backup
first when the app has local work.

## Compile-time features

The flags come from
`crosspad-core/include/crosspad/config/features.schema.json`, the
machine-readable twin of `Configuration.h`.

```bash
<wrapper> config                         # show the flags, * = changed
<wrapper> config FEAT_PAD_EDITOR off     # set one
<wrapper> config --gen                   # regenerate the build flags
```

Chosen values live in `crosspad.config.json`, never in the submodule header, so
configuring a build does not change `crosspad-core` for anyone else. Only
values that differ from the header default are written, to
`.crosspad/build_flags.cmake` (ESP-IDF and PC; the top-level `CMakeLists.txt`
includes it) and `.crosspad/build_flags.ini` (PlatformIO, applied by a `pre:`
extra script). An untouched project builds exactly as the headers say.
Developer tools → **Configure** shows the same catalog as a tree, with help
text and `requires` checks.

## Device check

```bash
<wrapper> device        # exit 2 when the device differs from the checkout
```

Every build records the app submodules it was made from (component, registry
id, commit, manifest pin, uncommitted changes) and reports them as `APPVER:`
lines on all three platforms:

| Platform | How it answers |
|---|---|
| ESP-IDF | `APP_VERSIONS` over USB CDC |
| Arduino | `APP_VERSIONS` on the serial console |
| PC | `./bin/CrossPad --versions` |

The manager compares that with the checkout; Developer tools → **Device** shows
the same. A board in the USB audio profile has no CDC: the SysEx
`F0 7D 1B 01 F7` on its MIDI port switches it back (with the USB serial guard
on, the board asks first). An app kept in the project rather than as a
submodule reports `ref=in-tree`, because its commit is the project's.

## Profiles

```bash
<wrapper> profile list
<wrapper> profile show lite       # what applying it would change
<wrapper> profile apply lite
```

A profile is a recipe: feature flags plus the app set with what each app
follows. `apply` shows the plan first. Apps the profile leaves out stay unless
you pass `--remove-extra`, and apps on `mine` or `version`, or with local work,
are never removed.

## New app from the TUI

Developer tools → **New app** is a form: fill in the id, name and description,
and press space on **Publish** to cycle *local only*, *private GitHub repo* and
*public GitHub repo*. The panel under the form shows what will be created: the
folder, the two sources to rewrite, the `REGISTER_APP_PL` line and, when
publishing, the repo name. Creating shows each step and ends on the build
command, with `[b]` to run it. What the template contains and the one rule it
shows (pad callbacks run on the pad thread and must not touch LVGL) are in
[`template/README.md.tmpl`](../template/README.md.tmpl).

## VS Code buttons

With the [VsCode Task Buttons](https://marketplace.visualstudio.com/items?itemName=spencerwmiles.vscode-task-buttons)
extension, the status bar gets buttons for the project's VS Code tasks:

| Project | Button | Task |
|---|---|---|
| platform-idf | `$(package) CP Tools` | `CrossPad: CP Tools` (the TUI) |
| platform-idf | `$(zap) OTA` | `CrossPad: OTA Flash` (flash the last build over USB CDC) |
| Arduino firmware | `$(package) App Manager` | `CrossPad: App Manager` |

platform-idf ships them in `.vscode/settings.template.json`; the one-line
installer merges that into `.vscode/settings.json` with this computer's paths.
By hand, copy the `VsCodeTaskButtons.tasks` block into `.vscode/settings.json`:

```json
{
    "VsCodeTaskButtons.tasks": [
        { "label": "$(package) CP Tools", "task": "CrossPad: CP Tools" },
        { "label": "$(zap) OTA", "task": "CrossPad: OTA Flash" }
    ]
}
```

The Arduino firmware already ships its button in its committed
`.vscode/settings.json`, so nothing needs copying there.
