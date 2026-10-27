# CrossPad App Registry

The app catalog of the CrossPad SDK, and the tools built around it:

- **`registry.json`**: every published CrossPad app, rebuilt by CI from GitHub (see [Registry contract](#registry-contract)).
- **`crosspad_app_manager.py`**: CP Tools, the app manager (command line and full-screen menu). Each platform has a thin wrapper that downloads it from here: `tools/app_manager.py` in platform-idf, `scripts/app_manager.py` in crosspad-pc.
- **`install/`**: the one-line installer for Windows, macOS and Linux.
- **`template/`**: the app template that `idf.py app-new` and `cptools new` generate from.

## Documentation

The CrossPad SDK docs are at **https://crosspad.app/docs/**:

- [Start here](https://crosspad.app/docs/start-here/): toolchain, first build, first flash
- [Install and remove apps](https://crosspad.app/docs/how-to/install-apps/), [Create a new app](https://crosspad.app/docs/how-to/new-app/), [Publish an app](https://crosspad.app/docs/how-to/publish-app/)
- [App catalog](https://crosspad.app/docs/reference/app-catalog/), generated from `registry.json`
- [Command-line tools](https://crosspad.app/docs/reference/cli/): CP Tools commands and the `idf.py app-*` actions
- [App manager](https://crosspad.app/docs/subsystems/app-manager/): screens, workspace policy, feature flags
- [Troubleshooting → Apps](https://crosspad.app/docs/troubleshooting/#apps)

Not on the site yet: [docs/app-manager.md](docs/app-manager.md) (what an app follows, backups, feature flags, the device check, profiles, the PC and Arduino wrappers, VS Code buttons).

## Quickstart

The recommended setup is by hand, with [Start here](https://crosspad.app/docs/start-here/). The shortcut is one line that installs everything and opens CP Tools. It takes 15–30 minutes the first time; run it again any time and it repairs only what is missing.

**Windows** (PowerShell)
```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/CrossPad/crosspad-apps/main/install/install.ps1 | iex"
```

**macOS / Linux**
```bash
curl -fsSL https://raw.githubusercontent.com/CrossPad/crosspad-apps/main/install/install.sh | bash
```

Step by step, with screenshots: [install/README.md](install/README.md). Afterwards open **CP Tools** from the desktop shortcut (Windows) or type `cptools`.

## Latest Updates

<!-- LATEST_UPDATES_START -->
- **Sampler v0.22.0** — the pads' meters through IPadMix (setMetering/takePeaks): the pitched instrument's PadMeters for a pitched kit, the platform's player.setPadMetering/takePadPeak otherwise -- what the Pad Mixer shows. Requires core 2.22.
- **Sampler v0.21.1** — the waveform cache's table (~9.7 kB of names and pointers the UI reads) in PSRAM where the board has it (EXT_RAM_BSS_ATTR), so internal RAM can pay for the 32 kB I-cache the render runs from.
- **Sampler v0.21.0** — picking a kit for a track opens on the list of its kind (KitSelectorConfig::list, kit_selector_app_pick_for(..., KitList)): Arrange's DRUMS on the drum kits, SLICE on the Slice kits, PERF on the rest. Requires core 2.6.
- **Sampler v0.20.0** — the kit types down the kit browser's left are PERF (was KITS), DRUMS, SLICE, PITCH, SONGS, USER -- six keys, 22 px each. SLICE lists the Slice kits ("engine": "slice", what the Slicer writes): one WAV in regions, one voice. Drums are told by KitInfo::isDrums(). Requires core 2.5.
- **Sampler v0.19.0** — the kit browser in the UX 2000 design -- KITS / DRUMS / PITCH / SONGS / USER down the left, five rows of the list on the right, what the highlighted thing is across the top, LOAD and EDIT below. DRUMS are the factory kits whose kit.json says "category": "drums"; PITCH the instruments saved in Pitch Play (LOAD opens one there) and the pitched kits; SONGS the projects on the card (LOAD opens one, then Arrange); USER the kits made on the board, the Recorder's takes (LOAD slices one in the Slicer) and + NEW KIT. The encoder turns the list and a click loads -- a long press leaves it for the keys; a finger drags it, taps a row, taps it again to load. The highlighted kit is heard once the list stands still, and the pads play and light it, read off the card on a worker of its own. LOAD shows the load's progress, and on the kit already loaded goes to the Sampler. EDIT is the card of the highlighted thing: pads, date, folder; for a kit of one's own its name, author, note and tempo and DELETE, as before. The covers and row thumbnails are gone. The gate is the platform's kit picker (core IKitPicker): Arrange's kit tracks pick their kit there, handed back, not loaded; an app opened for a song's second kit track is not held behind the gate. Requires core 2.2 (instrumentOpenRequest, readKitCopy, IKitPicker) and gui 2.2 (the kit browser's back is the app history).
- **Sampler v0.18.0** — builds on the PC simulator and with MSVC -- every RTOS call (waveform cache and loader, kit-load and kit-convert workers) goes through port/SamplerRtos.hpp, which keeps the board's PSRAM stacks, cores and priorities; the kit-selector gate (kit_gate) for every platform; the kit browser and waveform styles are the sampler's own, gui 2.0 no longer has them; a root deleted before the app's teardown is handled (gui 2.0 calls destroy with none); a waveform sweep that met a queue another thread had filled no longer ends the sweeps, so a kit with more layers than the queue gets them all; builds on core 1.70+/gui 1.28+ and on core/gui 2.x (>=1.70.0,<3.0.0 and >=1.28.0,<3.0.0) for the merge window
<!-- LATEST_UPDATES_END -->

## CrossPad Official

<!-- APP_TABLE_START -->
| App | Version | Description | Platforms | Requires | Repo |
|-----|---------|-------------|-----------|----------|------|
| **App Store** | 0.1.1 | Browse, install, and manage CrossPad apps from the registry | pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-appstore](https://github.com/CrossPad/crosspad-appstore) |
| **DAW Control** | 0.5.0 | DAW controller surface: pads play the DAW, the DAW lights the pads and fills the screen (FL Studio, Ableton Live, REAPER) | esp-idf, pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-dawcontrol](https://github.com/CrossPad/crosspad-dawcontrol) |
| **Pad Mixer** | 0.3.0 | Sixteen faders, one per pad | esp-idf, pc | core >=2.22.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-pad-mixer](https://github.com/CrossPad/crosspad-pad-mixer) |
| **Piano** | 0.1.2 | Synth piano with parameter sliders, presets, octave control | pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-piano](https://github.com/CrossPad/crosspad-piano) |
| **Pitch Play** | 0.10.4 | One sample or many, played chromatically on the pads and from a MIDI keyboard | esp-idf | core >=2.2.0,<3.0.0, gui >=2.0.0,<3.0.0 | [CrossPad/crosspad-pitchplay](https://github.com/CrossPad/crosspad-pitchplay) |
| **Pong** | 0.1.0 | Pong against the CPU over nine levels, or two players: encoder and pads as paddles, the pads light the court, square-wave effects; the one app of the pong firmware kit | pc, esp-idf | core >=2.0.0,<3.0.0, gui >=2.0.0,<3.0.0 | [CrossPad/crosspad-pong](https://github.com/CrossPad/crosspad-pong) |
| **Recorder** | 0.7.0 | Record a sample from the mics, the line-in or the pads, and trim it to a loop | esp-idf, pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-recorder](https://github.com/CrossPad/crosspad-recorder) |
| **Sampler** | 0.22.0 | Sample player with 16 pads, waveform editing, kit management | esp-idf, arduino | core >=2.22.0,<3.0.0, gui >=2.2.0,<3.0.0 | [CrossPad/crosspad-sampler](https://github.com/CrossPad/crosspad-sampler) |
| **Serial Monitor** | 0.1.1 | UART serial monitor with baud rate selection, auto-scroll, clear | pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-serial-monitor](https://github.com/CrossPad/crosspad-serial-monitor) |
| **Slicer** | 0.4.0 | Chop a loop into slices -- by its hits, into equal parts, or live on the pads -- and save it as a kit | esp-idf, pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-slicer](https://github.com/CrossPad/crosspad-slicer) |
| **Song** | 0.3.1 | Arrange scenes on a timeline | esp-idf, pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-song](https://github.com/CrossPad/crosspad-song) |

*11 official app(s)*
<!-- APP_TABLE_END -->

## Top 10 Community Apps

<!-- COMMUNITY_TOP_START -->
*No community apps yet — [add yours!](external-apps.json)*
<!-- COMMUNITY_TOP_END -->


## Registry contract

How an app gets into the catalog (walkthrough: [Publish an app](https://crosspad.app/docs/how-to/publish-app/)):

1. Its repo has a `crosspad-app.json` at the root. A repo without a readable one is skipped.
2. **CrossPad org repo:** it has the GitHub topic `crosspad-app`. **Any other repo:** it is public and listed in [`external-apps.json`](external-apps.json), added by pull request. CP Tools opens that pull request for you: Developer tools → **Submit an app to the catalog**.
3. The next registry build lists it (see below).

### `crosspad-app.json`

```json
{
  "id": "my-app",
  "name": "My App",
  "version": "0.1.0",
  "description": "What it does",
  "platforms": ["esp-idf", "pc"],
  "category": "music",
  "icon": "my-icon.png",
  "component_path": "components/crosspad-my-app",
  "requires": { "crosspad-core": ">=0.3.0", "crosspad-gui": ">=0.2.0" },
  "changelog": ["0.1.0: Initial release"]
}
```

| Field | | Meaning |
|---|---|---|
| `id` | required | The app's key in the catalog (`idf.py app-install --app <id>`). Without it the build uses the repo name minus `crosspad-` |
| `name`, `description` | required | Shown in CP Tools and the catalog |
| `version` | required | Semver `x.y.z` |
| `platforms` | required | Any of `esp-idf`, `pc`, `arduino` |
| `category` | | `music`, `audio`, `tools` or `other` (what `new --category` offers) |
| `icon` | | Icon file name |
| `component_path` | | Where the app goes in an ESP-IDF project |
| `requires` | | Minimum `crosspad-core` / `crosspad-gui` versions (a list means any version) |
| `screenshot` | | A path in the repo or a URL; CP Tools opens it from the app's page |
| `changelog` | | `"x.y.z: what changed"` entries; they feed Latest Updates above and are not copied into `registry.json` |

"Required" is what CP Tools checks before it submits an app; the template fills all five.

### `external-apps.json`

One entry per repo in `repos`. Only `repo` is needed; `url` defaults to `https://github.com/<repo>.git` and `branch` to the repo's default branch.

```json
{ "repo": "you/crosspad-my-app", "url": "https://github.com/you/crosspad-my-app.git", "branch": "main" }
```

A pull request that adds an entry is merged when the repo is public and outside the CrossPad org (org repos use the topic), its `crosspad-app.json` has the required fields and a semver version, and its `id` is not already in the catalog: the catalog is keyed by `id`, and a later entry replaces an earlier one without a warning.

### How the registry is built

[`build-registry.yml`](.github/workflows/build-registry.yml) runs [`build_registry.py`](build_registry.py) every 6 hours, when an app repo's release workflow sends `app-released`, on a push to `main` that changes `build_registry.py` or `external-apps.json`, and by hand (`workflow_dispatch`). It:

1. finds the CrossPad org repos with the `crosspad-app` topic and adds the repos in `external-apps.json`;
2. reads each repo's `crosspad-app.json` from its default branch (or the `branch` given);
3. writes `registry.json` (`{"version": 1, "apps": {"<id>": {name, version, description, repo, component_path, icon, category, platforms, requires, screenshot}}}`), the three generated blocks of this README and [`COMMUNITY_APPS.md`](COMMUNITY_APPS.md), and commits them as `chore: update registry.json [automated]`.

[`diff_registry.py`](diff_registry.py) compares the old and new registry and writes the new apps, new platforms and version changes as workflow outputs. Clients read `registry.json` from `main` over plain HTTPS (no GitHub account) and keep a copy in `app-registry.json` in the project for an hour.

Do not edit between the `<!-- …_START -->` and `<!-- …_END -->` markers: the build rewrites them.

## License

GPL-3.0-or-later — see [LICENSE](LICENSE).
