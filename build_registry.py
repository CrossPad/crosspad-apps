#!/usr/bin/env python3
"""Build registry.json by fetching crosspad-app.json from each app repo.

Reads app-sources.json for the list of repos, fetches each repo's
crosspad-app.json via GitHub API, and assembles registry.json.

Authentication: uses GITHUB_TOKEN env var, or falls back to `gh` CLI.
"""

import base64
import json
import os
import subprocess
import urllib.request
import urllib.error


def _get_github_token() -> str | None:
    """Get GitHub token from env or gh CLI."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def fetch_app_metadata(repo: str, token: str, branch: str = None) -> dict | None:
    """Fetch crosspad-app.json from a GitHub repo via API."""
    ref_param = f"?ref={branch}" if branch else ""
    url = f"https://api.github.com/repos/{repo}/contents/crosspad-app.json{ref_param}"
    headers = {
        "User-Agent": "crosspad-registry-builder",
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        content = base64.b64decode(data["content"]).decode()
        return json.loads(content)
    except urllib.error.HTTPError as e:
        print(f"  Warning: {repo} — HTTP {e.code}")
        return None
    except Exception as e:
        print(f"  Warning: {repo} — {e}")
        return None


def main():
    token = _get_github_token()
    if not token:
        print("Warning: No GitHub token found. Private repos will fail.")
        print("  Set GITHUB_TOKEN or install gh CLI.")

    with open("app-sources.json") as f:
        sources = json.load(f)

    apps = {}
    for source in sources.get("sources", []):
        repo = source["repo"]
        url = source["url"]
        print(f"Fetching {repo}...")

        meta = fetch_app_metadata(repo, token, branch=source.get("branch"))
        if not meta:
            continue

        app_id = meta.get("id", repo.split("/")[-1].replace("crosspad-", ""))
        apps[app_id] = {
            "name": meta.get("name", app_id),
            "description": meta.get("description", ""),
            "repo": url,
            "component_path": meta.get("component_path", f"components/crosspad-{app_id}"),
            "icon": meta.get("icon", ""),
            "category": meta.get("category", ""),
            "requires": meta.get("requires", []),
        }
        print(f"  -> {app_id}: {meta.get('name')}")

    registry = {
        "version": 1,
        "apps": apps,
    }

    with open("registry.json", "w") as f:
        json.dump(registry, f, indent=2)
        f.write("\n")

    print(f"\nBuilt registry.json with {len(apps)} apps.")


if __name__ == "__main__":
    main()
