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
- **Mixer v0.18.0** — setChannelTrimPan() -- a balance on top of a channel's own pan, never saved with the desk, as setChannelTrim() is to its fader: what an Arrange seq track's pan puts on the engine its notes play through while the song plays; the two multiply
- **Mixer v0.17.0** — a node that says its block added nothing (core 2.16.0 IAudioNode::lastMixSilent()) is metered as silent without a pass over its block -- in render() and renderOnly(); the buses and meters are the same to the bit. Requires core 2.16.
- **Mixer v0.16.1** — a channel slot gets its block of scratch when a channel is registered in it, not at setup() for all sixteen: with the scratch in internal RAM (core 2.15.0 AlignedVector) six unused slots were 3 kB of it.
- **Mixer v0.16.0** — + renderOnly(): the channels asked for, pulled and panned as render() leaves them, nothing sent to an output -- for a render no one hears (a freeze faster than real time), which renderTap() then reads.
- **Mixer v0.15.1** — MIXPROF gives each node's longest pass after its average (nodes=ch:avg/max): a spike says which node made it.
- **Mixer v0.15.0** — the Mixer in the UX 2000 design, sized for a finger: five tabs -- IN (inputs: GAIN or PAN, MON to every output heard, a row per socket, PAIR where the board has more inputs than ADCs), SOURCES (LEVEL or PAN, M, S), OUT (the masters and every output with a level of its own: LEVEL, M, LIM lit while the limiter works), ROUTE (a chip per source and output, CLEAR, RESET) and PRESETS (the desk saved and loaded by name, UNDO) -- rows with a 152 px zone a finger drags and two keys, the rest of a channel (sends, monitor, pan, an output's tone) behind its name; the engine is the only state, so anything else that moves the mix shows up here.
<!-- LATEST_UPDATES_END -->

## CrossPad Official

<!-- APP_TABLE_START -->
| App | Version | Description | Platforms | Requires | Repo |
|-----|---------|-------------|-----------|----------|------|
| **App Store** | 0.1.1 | Browse, install, and manage CrossPad apps from the registry | pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-appstore](https://github.com/CrossPad/crosspad-appstore) |
| **Mixer** | 0.18.0 | Audio mixer/router — dynamic IAudioNode channels, multi-output routing | pc, esp-idf | core >=2.16.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-mixer](https://github.com/CrossPad/crosspad-mixer) |
| **Recorder** | 0.7.0 | Record a sample from the mics, the line-in or the pads, and trim it to a loop | esp-idf, pc | core >=1.70.0,<3.0.0, gui >=1.28.0,<3.0.0 | [CrossPad/crosspad-recorder](https://github.com/CrossPad/crosspad-recorder) |

*3 official app(s)*
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
