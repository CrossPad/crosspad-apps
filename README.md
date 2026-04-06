# CrossPad App Registry

Central registry of available CrossPad applications. Auto-discovered from GitHub repos with the `crosspad-app` topic, plus external repos listed in `external-apps.json`.

## Available Apps

<!-- APP_TABLE_START -->
| App | Description | Category | Repo |
|-----|-------------|----------|------|
| **Sampler** | Sample player with 16 pads, waveform editing, kit management | music | [CrossPad/crosspad-sampler](https://github.com/CrossPad/crosspad-sampler) |
| **Sequencer** | MIDI step sequencer with recording, playback, overdub | music | [CrossPad/crosspad-sequencer](https://github.com/CrossPad/crosspad-sequencer) |
| **Synthesizer** | Polyphonic synth with 3 oscillators, ADSR, filter, effects | music | [CrossPad/crosspad-synthesizer](https://github.com/CrossPad/crosspad-synthesizer) |

*3 app(s) available*
<!-- APP_TABLE_END -->

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
