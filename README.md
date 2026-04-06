# CrossPad App Registry

Central registry of available CrossPad applications. Auto-discovered from GitHub repos with the `crosspad-app` topic.

## How It Works

1. Each app repo has the GitHub topic `crosspad-app` and contains a `crosspad-app.json` with metadata
2. CI runs `build_registry.py` which discovers all repos with the `crosspad-app` topic in the CrossPad org
3. The result is `registry.json` — a single file consumed by the CrossPad app manager (`idf.py app-*` commands)

## Adding a New App

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

## Usage (from platform-idf)

```bash
idf.py app-list                  # List available apps
idf.py app-install --app sampler # Install
idf.py app-remove --app sampler  # Remove
idf.py app-update --app sampler  # Update
idf.py app-update --all          # Update all
```

## Files

- `build_registry.py` — Discovers repos by topic, fetches metadata, builds registry
- `registry.json` — Auto-generated registry (consumed by app manager)
