#!/usr/bin/env python3
"""Compare old and new registry.json, output change summaries for CI.

Sets GitHub Actions outputs:
  new_apps         — markdown lines for newly added apps
  new_platforms    — markdown lines for apps that gained new platform support
  version_updates  — markdown lines for apps with version bumps
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
        plat_str = ", ".join(platforms) if platforms else "all"
        desc = info.get("description", "")

        if app_id not in old_apps:
            added.append(f"**{name}** v{version} ({plat_str}) — {desc}")
            continue

        old_info = old_apps[app_id]

        # Platform changes
        old_plats = set(old_info.get("platforms", []))
        new_plats = set(platforms)
        gained = new_plats - old_plats
        if gained:
            platform_changes.append(f"**{name}** now supports: {', '.join(gained)}")

        # Version changes
        old_ver = old_info.get("version", "")
        if version and version != old_ver:
            version_changes.append(f"**{name}** {old_ver} → {version}")

    # Write to GitHub Actions outputs
    output_file = os.environ.get("GITHUB_OUTPUT", "")
    if output_file:
        with open(output_file, "a") as f:
            _write_multiline(f, "new_apps", added)
            _write_multiline(f, "new_platforms", platform_changes)
            _write_multiline(f, "version_updates", version_changes)
    else:
        # Local testing
        if added:
            print(f"New apps:\n" + "\n".join(f"  {a}" for a in added))
        if platform_changes:
            print(f"Platform changes:\n" + "\n".join(f"  {p}" for p in platform_changes))
        if version_changes:
            print(f"Version updates:\n" + "\n".join(f"  {v}" for v in version_changes))
        if not added and not platform_changes and not version_changes:
            print("No changes detected.")


def _write_multiline(f, name, lines):
    if lines:
        text = "\\n".join(lines)
        f.write(f"{name}={text}\n")
    else:
        f.write(f"{name}=\n")


if __name__ == "__main__":
    main()
