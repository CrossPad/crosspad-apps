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
- **Mixer v0.11.0** — desk format 4 -- a saved channel is loaded onto the live channel of the same name wherever it now sits (the slot is only a hint), so a desk saved before the native sampler's Sampler2 channel (or with it, on a build without it) keeps USB, Click and the inputs on USB, Click and the inputs; earlier desks lost those channels' settings to the name guard. The desk's JSON moved to MixerState.cpp so a platform builds it -Os and the render -O2; tests/test_desk_migration.cpp
- **Mixer v0.10.0** — 0.8.1 (master: input pairs, silent channels skipped, NaN kept off the buses) and 0.9.1 (the engine branch: Source switch, IN as USB/Line/Mic, EQ across the outputs, per-channel render timing) merged; the look-up table files both the IN1/IN2/IN3 and the Line/Mic channel names
- **Mixer v0.9.1** — saveState()/loadState() through stdio instead of fstream (smaller firmware image); same file, same .tmp/.bak commit and fallback
- **Arrange v0.9.0** — the status line sits in the status bar, centred where the CrossPad logo was (gui 1.17 statusbar_show_title), and the row it took goes to the tools at the foot: as tall as the screen leaves them, in the larger font, spread across the width; MOVE reads its axis as two arrows; requires gui 1.17
- **Mixer v0.9.0** — IN reads USB in, In 1/2, In 3/4, Mic. The two line sockets share one converter, so they are two rows over one channel: the one the converter is on is live, the other is dimmed, and tapping it makes it live. Also fixes the page they were filed under -- the look-up table still said IN1/IN2 after the platform renamed the channels Mic and Line, which quietly put both on SOURCES.
- **Mixer v0.8.1 (0.7.2 merged in)** — render() neither pans nor sends a channel whose block is silent (peak 0) -- the buses come out bit for bit the same, and every quiet channel saves two passes per send; a block of only NaN and zeros no longer reaches the buses (renderTap() still sums it); host tests in tests/, the scalar and the esp-dsp path
<!-- LATEST_UPDATES_END -->

## CrossPad Official

<!-- APP_TABLE_START -->
| App | Version | Description | Platforms | Requires | Repo |
|-----|---------|-------------|-----------|----------|------|
| **App Store** | 0.1.0 | Browse, install, and manage CrossPad apps from the registry | pc | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-appstore](https://github.com/CrossPad/crosspad-appstore) |
| **Arrange** | 0.9.0 | Four audio tracks of bounced clips on a timeline | esp-idf, pc | core >=1.34.0, gui >=1.17.0 | [CrossPad/crosspad-arrange](https://github.com/CrossPad/crosspad-arrange) |
| **DAW Control** | 0.4.1 | DAW controller surface: pads to the DAW, LED/text feedback from it (FL Studio, Ableton, REAPER); launches the DAW through the host hub | esp-idf, pc | core >=1.23.0, gui >=1.3.0 | [CrossPad/crosspad-dawcontrol](https://github.com/CrossPad/crosspad-dawcontrol) |
| **Instructions** | 0.2.0 | Markdown-based instructions and help viewer | esp-idf, arduino, pc | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-instructions](https://github.com/CrossPad/crosspad-instructions) |
| **Mixer** | 0.12.0 | Audio mixer/router — dynamic IAudioNode channels, multi-output routing | pc, esp-idf | core >=1.44.0, gui >=1.14.0 | [CrossPad/crosspad-mixer](https://github.com/CrossPad/crosspad-mixer) |
| **Pad Mixer** | 0.2.1 | Sixteen faders, one per pad | esp-idf, pc | core >=1.21.0, gui >=1.12.0 | [CrossPad/crosspad-pad-mixer](https://github.com/CrossPad/crosspad-pad-mixer) |
| **Piano** | 0.1.0 | Synth piano with parameter sliders, presets, octave control | pc | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-piano](https://github.com/CrossPad/crosspad-piano) |
| **Pitch Play** | 0.5.0 | One sample or many, played chromatically on the pads and from a MIDI keyboard | esp-idf | core >=1.38.0, gui >=1.18.0 | [CrossPad/crosspad-pitchplay](https://github.com/CrossPad/crosspad-pitchplay) |
| **Recorder** | 0.4.2 | Record a sample from the mics, the line-in or the pads, and trim it to a loop | esp-idf, pc | core >=1.28.0, gui >=1.14.0 | [CrossPad/crosspad-recorder](https://github.com/CrossPad/crosspad-recorder) |
| **Sampler** | 0.8.4 | Sample player with 16 pads, waveform editing, kit management | esp-idf, arduino | core >=1.45.0, gui >=1.16.0 | [CrossPad/crosspad-sampler](https://github.com/CrossPad/crosspad-sampler) |
| **Sequencer** | 0.6.0 | Record, loop and erase scenes on the pads | esp-idf, pc | core >=1.23.0, gui >=1.13.0 | [CrossPad/crosspad-pattern-seq](https://github.com/CrossPad/crosspad-pattern-seq) |
| **Serial Monitor** | 0.1.0 | UART serial monitor with baud rate selection, auto-scroll, clear | pc | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-serial-monitor](https://github.com/CrossPad/crosspad-serial-monitor) |
| **Slicer** | 0.3.1 | Chop a loop into slices -- by its hits, into equal parts, or live on the pads -- and save it as a kit | esp-idf, pc | core >=1.31.0, gui >=1.14.0 | [CrossPad/crosspad-slicer](https://github.com/CrossPad/crosspad-slicer) |
| **Song** | 0.2.0 | Arrange scenes on a timeline | esp-idf, pc | core >=1.21.0, gui >=1.12.0 | [CrossPad/crosspad-song](https://github.com/CrossPad/crosspad-song) |
| **Synthesizer** | 0.1.0 | Polyphonic synth with 3 oscillators, ADSR, filter, effects | arduino | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-synthesizer](https://github.com/CrossPad/crosspad-synthesizer) |

*15 official app(s)*
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
