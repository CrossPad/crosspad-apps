#!/usr/bin/env python3
"""Build registry.json by discovering CrossPad app repos via GitHub topic.

Searches for repos with the 'crosspad-app' topic in the CrossPad org,
fetches each repo's crosspad-app.json, and assembles registry.json.

Authentication: uses GITHUB_TOKEN env var, or falls back to `gh` CLI.
"""

import base64
import json
import os
import subprocess
import urllib.request
import urllib.error

ORG = "CrossPad"
TOPIC = "crosspad-app"


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


def _api_get(url: str, token: str) -> dict | None:
    headers = {
        "User-Agent": "crosspad-registry-builder",
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        print(f"  Warning: {url} — {e}")
        return None


def discover_app_repos(token: str) -> list[dict]:
    """Find all repos in the org with the crosspad-app topic."""
    repos = []
    page = 1
    while True:
        url = f"https://api.github.com/search/repositories?q=org:{ORG}+topic:{TOPIC}&per_page=100&page={page}"
        data = _api_get(url, token)
        if not data or not data.get("items"):
            break
        for item in data["items"]:
            repos.append({
                "full_name": item["full_name"],
                "clone_url": item["clone_url"],
                "default_branch": item["default_branch"],
            })
        if len(data["items"]) < 100:
            break
        page += 1
    return repos


def fetch_app_metadata(repo: str, token: str, branch: str = None) -> dict | None:
    """Fetch crosspad-app.json from a GitHub repo via API."""
    ref_param = f"?ref={branch}" if branch else ""
    url = f"https://api.github.com/repos/{repo}/contents/crosspad-app.json{ref_param}"
    data = _api_get(url, token)
    if not data or "content" not in data:
        return None
    try:
        content = base64.b64decode(data["content"]).decode()
        return json.loads(content)
    except Exception as e:
        print(f"  Warning: {repo} — failed to parse crosspad-app.json: {e}")
        return None


def main():
    token = _get_github_token()
    if not token:
        print("Warning: No GitHub token found. Private repos will fail.")
        print("  Set GITHUB_TOKEN or install gh CLI.")

    print(f"Discovering repos with topic '{TOPIC}' in {ORG}...")
    repos = discover_app_repos(token)
    print(f"Found {len(repos)} repo(s).\n")

    apps = {}
    for repo_info in repos:
        repo = repo_info["full_name"]
        clone_url = repo_info["clone_url"]
        branch = repo_info["default_branch"]
        print(f"Fetching {repo} ({branch})...")

        meta = fetch_app_metadata(repo, token, branch=branch)
        if not meta:
            print(f"  Skipped (no valid crosspad-app.json)")
            continue

        app_id = meta.get("id", repo.split("/")[-1].replace("crosspad-", ""))
        apps[app_id] = {
            "name": meta.get("name", app_id),
            "description": meta.get("description", ""),
            "repo": clone_url,
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
