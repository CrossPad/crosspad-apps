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
- **Arrange v0.26.0** — everything by itself (core 2.26). With the song stopped every seq track ARM is not on that is not frozen as it is freezes -- the one ARM left, one gone stale after a tempo turned or a kit loaded --, a failed freeze tried again later; an element block only the engine can bake (its kit tracks frozen at another tempo) is rebaked by itself after 3 s untouched, the note saying which and why, instead of waiting for EDIT > Rebake now; a Pitch sound that would not load is asked for again and said; the song list pages (24 a page, from the open song's, Back / More) so every song can be opened. Requires core 2.26.
- **Arrange v0.25.0** — elements -- the song around them (core 2.25). With the song stopped and no pad played for 5 s Arrange tells the engine it may bake the other songs' blocks of an element changed since; a block whose element changed under it (a new tempo, a kit saved) plays as it was and says old until EDIT > Rebake now, which enters and leaves its element with the processing box over the lanes. A bake under way shows on its block. Requires core 2.25.
- **Arrange v0.24.0** — elements -- arrangements inside the song (core 2.23). EDIT > New element here lays a four-bar element on a free audio track and opens it; Element from library lays one already made. An element block is ice blue with a layers glyph and its title (dimmed, not baked, until its first leave); CLIP EDIT on it opens it as the song, the context row becomes the breadcrumb SONG > ELEMENT 1 (three levels at most, ... for the rest, a tap goes up to that level), and the power button's click goes one level up, freezing and baking what changed, with the processing box saying how far. Requires core 2.23.
- **Arrange v0.23.0** — MIX looks like a DAW's mixer -- each strip has the track's number and kind (or name) in its colour, PAN (C / L25 / R40, a tap on its reading centres it; kept with the song, core 2.21 SongTrack::pan), the fader with the track's stereo meter beside it (after the fader and pan, the lanes' scale: green, amber from -6 dB, red from -1), the dB, and M and S side by side; requires core 2.21
- **Arrange v0.22.0** — an audio track's input sheet (a long press on its header) has MONITOR: the input it records heard live on the speakers and jacks, or not -- the Mixer's MONITOR at all or off for that input's channels (MIC+LINE both), shown in the Mixer and kept with its desk; absent for the pads, heard anyway; requires core 2.20 (IInputMonitor)
- **Sampler v0.22.0** — the pads' meters through IPadMix (setMetering/takePeaks): the pitched instrument's PadMeters for a pitched kit, the platform's player.setPadMetering/takePadPeak otherwise -- what the Pad Mixer shows. Requires core 2.22.
<!-- LATEST_UPDATES_END -->

## CrossPad Official

<!-- APP_TABLE_START -->
| App | Version | Description | Platforms | Requires | Repo |
|-----|---------|-------------|-----------|----------|------|
| **App Store** | 0.1.1 | Browse, install, and manage CrossPad apps from the registry | pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-appstore](https://github.com/CrossPad/crosspad-appstore) |
| **Arrange** | 0.26.0 | Four audio tracks of bounced clips on a timeline | esp-idf, pc | core >=2.26.0,<3.0.0, gui >=2.0.0,<3.0.0 | [CrossPad/crosspad-arrange](https://github.com/CrossPad/crosspad-arrange) |
| **DAW Control** | 0.5.0 | DAW controller surface: pads play the DAW, the DAW lights the pads and fills the screen (FL Studio, Ableton Live, REAPER) | esp-idf, pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-dawcontrol](https://github.com/CrossPad/crosspad-dawcontrol) |
| **DOOM** | 0.1.0 | DOOM (doomgeneric) on the pads, the encoder and the panel; the one app of the doom firmware kit | pc, esp-idf | core >=2.0.0,<3.0.0, gui >=2.0.0,<3.0.0 | [CrossPad/crosspad-doom](https://github.com/CrossPad/crosspad-doom) |
| **Instructions** | 0.3.0 | Markdown-based instructions and help viewer | esp-idf, arduino, pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-instructions](https://github.com/CrossPad/crosspad-instructions) |
| **Mixer** | 0.18.0 | Audio mixer/router — dynamic IAudioNode channels, multi-output routing | pc, esp-idf | core >=2.16.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-mixer](https://github.com/CrossPad/crosspad-mixer) |
| **Pad Mixer** | 0.3.0 | Sixteen faders, one per pad | esp-idf, pc | core >=2.22.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-pad-mixer](https://github.com/CrossPad/crosspad-pad-mixer) |
| **Piano** | 0.1.2 | Synth piano with parameter sliders, presets, octave control | pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-piano](https://github.com/CrossPad/crosspad-piano) |
| **Piano Tiles** | 0.1.0 | Piano Tiles for the pads: tiles fall in four lanes, the pads show what comes, each tile plays the next note of a public-domain tune on a small piano synth; levels speed it up, best scores saved on the card; the one app of the pianotiles firmware kit | pc, esp-idf | core >=2.0.0,<3.0.0, gui >=2.0.0,<3.0.0 | [CrossPad/crosspad-pianotiles](https://github.com/CrossPad/crosspad-pianotiles) |
| **Pitch Play** | 0.10.4 | One sample or many, played chromatically on the pads and from a MIDI keyboard | esp-idf | core >=2.2.0,<3.0.0, gui >=2.0.0,<3.0.0 | [CrossPad/crosspad-pitchplay](https://github.com/CrossPad/crosspad-pitchplay) |
| **Pong** | 0.1.0 | Pong against the CPU over nine levels, or two players: encoder and pads as paddles, the pads light the court, square-wave effects; the one app of the pong firmware kit | pc, esp-idf | core >=2.0.0,<3.0.0, gui >=2.0.0,<3.0.0 | [CrossPad/crosspad-pong](https://github.com/CrossPad/crosspad-pong) |
| **Recorder** | 0.7.0 | Record a sample from the mics, the line-in or the pads, and trim it to a loop | esp-idf, pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-recorder](https://github.com/CrossPad/crosspad-recorder) |
| **Sampler** | 0.22.0 | Sample player with 16 pads, waveform editing, kit management | esp-idf, arduino | core >=2.22.0,<3.0.0, gui >=2.2.0,<3.0.0 | [CrossPad/crosspad-sampler](https://github.com/CrossPad/crosspad-sampler) |
| **Sequencer** | 0.10.1 | Record, loop and erase scenes on the pads | esp-idf, pc | core >=2.7.0,<3.0.0, gui >=2.0.0,<3.0.0 | [CrossPad/crosspad-pattern-seq](https://github.com/CrossPad/crosspad-pattern-seq) |
| **Serial Monitor** | 0.1.1 | UART serial monitor with baud rate selection, auto-scroll, clear | pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-serial-monitor](https://github.com/CrossPad/crosspad-serial-monitor) |
| **Slicer** | 0.4.0 | Chop a loop into slices -- by its hits, into equal parts, or live on the pads -- and save it as a kit | esp-idf, pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-slicer](https://github.com/CrossPad/crosspad-slicer) |
| **Song** | 0.3.1 | Arrange scenes on a timeline | esp-idf, pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-song](https://github.com/CrossPad/crosspad-song) |
| **Synthesizer** | 0.1.0 | Polyphonic synth with 3 oscillators, ADSR, filter, effects | arduino | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-synthesizer](https://github.com/CrossPad/crosspad-synthesizer) |

*18 official app(s)*
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
