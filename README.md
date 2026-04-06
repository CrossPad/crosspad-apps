# CrossPad App Registry

Central registry of available CrossPad applications. Auto-generated from individual app repositories.

## How It Works

1. Each app repo contains a `crosspad-app.json` with metadata (name, description, icon, dependencies)
2. CI runs `build_registry.py` which fetches metadata from all app repos listed in `app-sources.json`
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

2. Add your repo to `app-sources.json` in this registry:
   ```json
   {
     "repo": "CrossPad/crosspad-my-app",
     "url": "https://github.com/CrossPad/crosspad-my-app.git"
   }
   ```

3. CI will auto-update `registry.json` on next run, or trigger manually.

## Usage (from platform-idf)

```bash
idf.py app-list                  # List available apps
idf.py app-install --app sampler # Install
idf.py app-remove --app sampler  # Remove
idf.py app-update --app sampler  # Update
idf.py app-update --all          # Update all
```

## Files

- `app-sources.json` — List of app repos to index
- `build_registry.py` — Script that builds `registry.json` from app repos
- `registry.json` — Auto-generated registry (consumed by app manager)
