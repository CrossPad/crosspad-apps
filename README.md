# CrossPad App Registry

Central registry of available CrossPad applications. Auto-discovered from GitHub repos with the `crosspad-app` topic, plus external repos listed in `external-apps.json`.

> **Want to publish your app?** See [How It Works](#how-it-works) for setup instructions.

## Latest Updates

<!-- LATEST_UPDATES_START -->
- **Sequencer v0.2.0** — Pad logic refactor, portable UI components
- **Sampler v0.1.0** — Initial release — pad playback, waveform view, kit selector
- **Synthesizer v0.1.0** — Initial release — 3 oscillators, ADSR, delay + reverb effects
- **Sequencer v0.1.0** — Initial release — step sequencer with MIDI recording
<!-- LATEST_UPDATES_END -->

## CrossPad Official

<!-- APP_TABLE_START -->
| App | Version | Description | Platforms | Requires | Repo |
|-----|---------|-------------|-----------|----------|------|
| **Sampler** | 0.1.0 | Sample player with 16 pads, waveform editing, kit management | esp-idf, arduino | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-sampler](https://github.com/CrossPad/crosspad-sampler) |
| **Sequencer** | 0.2.0 | MIDI step sequencer with recording, playback, overdub | arduino | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-sequencer](https://github.com/CrossPad/crosspad-sequencer) |
| **Synthesizer** | 0.1.0 | Polyphonic synth with 3 oscillators, ADSR, filter, effects | arduino | core >=0.3.0, gui >=0.2.0 | [CrossPad/crosspad-synthesizer](https://github.com/CrossPad/crosspad-synthesizer) |

*3 official app(s)*
<!-- APP_TABLE_END -->

## Top 10 Community Apps

<!-- COMMUNITY_TOP_START -->
*No community apps yet — [add yours!](external-apps.json)*
<!-- COMMUNITY_TOP_END -->

## How It Works

1. Each app repo has the GitHub topic `crosspad-app` and contains a `crosspad-app.json` with metadata
2. CI runs `build_registry.py` which:
   - Discovers all repos with the `crosspad-app` topic in the CrossPad org
   - Merges in any external repos from `external-apps.json`
3. The result is `registry.json` — consumed by the CrossPad app manager (`idf.py app-*` commands)

## Adding a CrossPad Org App

1. Add `crosspad-app.json` to your app repository:
   ```json
   {
     "name": "My App",
     "id": "my-app",
     "description": "What it does",
     "category": "music",
     "icon": "my-icon.png",
     "requires": ["crosspad-core", "crosspad-gui"],
     "component_path": "components/crosspad-my-app"
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

## Usage (from platform-idf)

```bash
idf.py app-list                  # List available apps
idf.py app-install --app sampler # Install
idf.py app-remove --app sampler  # Remove
idf.py app-update --app sampler  # Update
idf.py app-update --all          # Update all
```

## Files

- `build_registry.py` — Discovers repos by topic + external list, builds registry
- `external-apps.json` — Community/third-party app repos (add via PR)
- `registry.json` — Auto-generated registry (consumed by app manager)
