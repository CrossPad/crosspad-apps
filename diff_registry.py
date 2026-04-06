#!/usr/bin/env python3
"""Compare old and new registry.json, output change details for CI.

Sets GitHub Actions outputs as JSON arrays for rich Discord embeds:
  new_apps_json       — JSON array of {name, version, description, platforms, repo}
  new_platforms_json   — JSON array of {name, version, gained, all_platforms, repo}
  version_updates_json — JSON array of {name, old_version, new_version, repo}
  has_new_apps         — "true" or "false"
  has_new_platforms    — "true" or "false"
  has_version_updates  — "true" or "false"
"""

import json
import os
import sys


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <old_registry.json> <new_registry.json>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        old = json.load(f)
    with open(sys.argv[2]) as f:
        new = json.load(f)

    old_apps = old.get("apps", {})
    new_apps = new.get("apps", {})

    added = []
    platform_changes = []
    version_changes = []

    for app_id, info in new_apps.items():
        name = info.get("name", app_id)
        version = info.get("version", "")
        platforms = info.get("platforms", [])
        desc = info.get("description", "")
        category = info.get("category", "")
        repo = info.get("repo", "").replace(".git", "")

        if app_id not in old_apps:
            added.append({
                "name": name,
                "version": version,
                "description": desc,
                "platforms": ", ".join(platforms) if platforms else "all",
                "category": category,
                "repo": repo,
            })
            continue

        old_info = old_apps[app_id]

        # Platform changes
        old_plats = set(old_info.get("platforms", []))
        new_plats = set(platforms)
        gained = new_plats - old_plats
        if gained:
            platform_changes.append({
                "name": name,
                "version": version,
                "gained": ", ".join(sorted(gained)),
                "all_platforms": ", ".join(sorted(platforms)) if platforms else "all",
                "repo": repo,
            })

        # Version changes
        old_ver = old_info.get("version", "")
        if version and version != old_ver:
            version_changes.append({
                "name": name,
                "old_version": old_ver,
                "new_version": version,
                "repo": repo,
            })

    # Write to GitHub Actions outputs
    output_file = os.environ.get("GITHUB_OUTPUT", "")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"new_apps_json={json.dumps(added)}\n")
            f.write(f"new_platforms_json={json.dumps(platform_changes)}\n")
            f.write(f"version_updates_json={json.dumps(version_changes)}\n")
            f.write(f"has_new_apps={'true' if added else 'false'}\n")
            f.write(f"has_new_platforms={'true' if platform_changes else 'false'}\n")
            f.write(f"has_version_updates={'true' if version_changes else 'false'}\n")
    else:
        # Local testing
        if added:
            print("New apps:")
            for a in added:
                print(f"  {a['name']} v{a['version']} ({a['platforms']}) — {a['description']}")
        if platform_changes:
            print("Platform changes:")
            for p in platform_changes:
                print(f"  {p['name']} v{p['version']} gained: {p['gained']} (now: {p['all_platforms']})")
        if version_changes:
            print("Version updates:")
            for v in version_changes:
                print(f"  {v['name']} {v['old_version']} → {v['new_version']}")
        if not added and not platform_changes and not version_changes:
            print("No changes detected.")


if __name__ == "__main__":
    main()
