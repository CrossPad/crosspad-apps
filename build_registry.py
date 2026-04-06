#!/usr/bin/env python3
"""Build registry.json by discovering CrossPad app repos via GitHub topic.

Searches for repos with the 'crosspad-app' topic in the CrossPad org,
fetches each repo's crosspad-app.json, and assembles registry.json.
Also generates README tables and COMMUNITY_APPS.md.

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
TOP_COMMUNITY_COUNT = 10


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
                "stars": item.get("stargazers_count", 0),
                "source": "official",
            })
        if len(data["items"]) < 100:
            break
        page += 1
    return repos


def fetch_repo_stars(repo: str, token: str) -> int:
    """Fetch star count for a repo."""
    data = _api_get(f"https://api.github.com/repos/{repo}", token)
    if data:
        return data.get("stargazers_count", 0)
    return 0


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


def load_external_repos(token: str) -> list[dict]:
    """Load external (non-org) repos from external-apps.json, fetch star counts."""
    path = os.path.join(os.path.dirname(__file__), "external-apps.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        data = json.load(f)
    repos = []
    for entry in data.get("repos", []):
        repo_name = entry["repo"]
        stars = fetch_repo_stars(repo_name, token)
        repos.append({
            "full_name": repo_name,
            "clone_url": entry.get("url", f"https://github.com/{repo_name}.git"),
            "default_branch": entry.get("branch"),
            "stars": stars,
            "source": "community",
        })
    return repos


def build_app_entry(meta: dict, clone_url: str, stars: int, source: str) -> dict:
    """Build a normalized app entry from metadata."""
    raw_requires = meta.get("requires", {})
    if isinstance(raw_requires, list):
        requires = {r: "*" for r in raw_requires}
    else:
        requires = raw_requires

    return {
        "name": meta.get("name", ""),
        "description": meta.get("description", ""),
        "repo": clone_url,
        "component_path": meta.get("component_path", ""),
        "icon": meta.get("icon", ""),
        "category": meta.get("category", ""),
        "platforms": meta.get("platforms", []),
        "requires": requires,
        "stars": stars,
        "source": source,
    }


def main():
    token = _get_github_token()
    if not token:
        print("Warning: No GitHub token found. Private repos will fail.")
        print("  Set GITHUB_TOKEN or install gh CLI.")

    # 1. Auto-discover from org topic
    print(f"Discovering repos with topic '{TOPIC}' in {ORG}...")
    repos = discover_app_repos(token)
    print(f"Found {len(repos)} org repo(s).")

    # 2. Add external repos
    external = load_external_repos(token)
    if external:
        print(f"Found {len(external)} external repo(s).")
        seen = {r["full_name"] for r in repos}
        for ext in external:
            if ext["full_name"] not in seen:
                repos.append(ext)
                seen.add(ext["full_name"])
    print()

    apps = {}
    for repo_info in repos:
        repo = repo_info["full_name"]
        clone_url = repo_info["clone_url"]
        branch = repo_info["default_branch"]
        stars = repo_info.get("stars", 0)
        source = repo_info.get("source", "official")
        print(f"Fetching {repo} ({branch or 'default'})...")

        meta = fetch_app_metadata(repo, token, branch=branch)
        if not meta:
            print(f"  Skipped (no valid crosspad-app.json)")
            continue

        app_id = meta.get("id", repo.split("/")[-1].replace("crosspad-", ""))
        apps[app_id] = build_app_entry(meta, clone_url, stars, source)
        print(f"  -> {app_id}: {meta.get('name')} ({source}, {stars} stars)")

    # Write registry (without stars/source - those are build-time only)
    registry_apps = {}
    for app_id, info in apps.items():
        registry_apps[app_id] = {k: v for k, v in info.items() if k not in ("stars", "source")}

    registry = {"version": 1, "apps": registry_apps}
    with open("registry.json", "w") as f:
        json.dump(registry, f, indent=2)
        f.write("\n")

    update_readme(apps)
    update_community_apps(apps)
    print(f"\nBuilt registry.json with {len(apps)} apps.")


def _app_table_row(app_id: str, info: dict, show_stars: bool = False) -> str:
    name = info.get("name", app_id)
    desc = info.get("description", "")
    platforms = info.get("platforms", [])
    platform_str = ", ".join(platforms) if platforms else "all"
    requires = info.get("requires", {})
    req_parts = []
    for dep, ver in requires.items():
        short = dep.replace("crosspad-", "")
        req_parts.append(f"{short} {ver}" if ver != "*" else short)
    req_str = ", ".join(req_parts) if req_parts else "-"
    repo_url = info.get("repo", "").replace(".git", "")
    repo_name = repo_url.split("github.com/")[-1] if "github.com" in repo_url else repo_url

    if show_stars:
        stars = info.get("stars", 0)
        return f"| **{name}** | {desc} | {platform_str} | {req_str} | {stars} | [{repo_name}]({repo_url}) |"
    return f"| **{name}** | {desc} | {platform_str} | {req_str} | [{repo_name}]({repo_url}) |"


def update_readme(apps: dict):
    """Update README.md with official apps table and top community apps."""
    readme_path = os.path.join(os.path.dirname(__file__), "README.md")
    if not os.path.exists(readme_path):
        return

    with open(readme_path) as f:
        content = f.read()

    # Official apps
    official = {k: v for k, v in apps.items() if v.get("source") == "official"}
    community = {k: v for k, v in apps.items() if v.get("source") == "community"}

    # --- Official table ---
    start, end = "<!-- APP_TABLE_START -->", "<!-- APP_TABLE_END -->"
    if start in content:
        lines = [
            "| App | Description | Platforms | Requires | Repo |",
            "|-----|-------------|-----------|----------|------|",
        ]
        for app_id, info in sorted(official.items()):
            lines.append(_app_table_row(app_id, info))
        lines.append(f"\n*{len(official)} official app(s)*")

        si = content.index(start) + len(start)
        ei = content.index(end)
        content = content[:si] + "\n" + "\n".join(lines) + "\n" + content[ei:]

    # --- Top community table ---
    start2, end2 = "<!-- COMMUNITY_TOP_START -->", "<!-- COMMUNITY_TOP_END -->"
    if start2 in content:
        top = sorted(community.items(), key=lambda x: x[1].get("stars", 0), reverse=True)[:TOP_COMMUNITY_COUNT]
        if top:
            lines = [
                "| App | Description | Platforms | Requires | Stars | Repo |",
                "|-----|-------------|-----------|----------|-------|------|",
            ]
            for app_id, info in top:
                lines.append(_app_table_row(app_id, info, show_stars=True))
            lines.append(f"\n*Showing top {len(top)} of {len(community)} community app(s) by stars — [see all](COMMUNITY_APPS.md)*")
        else:
            lines = ["*No community apps yet — [add yours!](external-apps.json)*"]

        si = content.index(start2) + len(start2)
        ei = content.index(end2)
        content = content[:si] + "\n" + "\n".join(lines) + "\n" + content[ei:]

    with open(readme_path, "w") as f:
        f.write(content)


def update_community_apps(apps: dict):
    """Generate COMMUNITY_APPS.md with all community apps sorted by stars."""
    community = {k: v for k, v in apps.items() if v.get("source") == "community"}
    sorted_apps = sorted(community.items(), key=lambda x: x[1].get("stars", 0), reverse=True)

    lines = [
        "# Community Apps",
        "",
        "All community-contributed CrossPad applications, sorted by GitHub stars.",
        "",
        "Want to add your app? Open a PR to [external-apps.json](external-apps.json).",
        "",
    ]

    if sorted_apps:
        lines.extend([
            "| App | Description | Platforms | Requires | Stars | Repo |",
            "|-----|-------------|-----------|----------|-------|------|",
        ])
        for app_id, info in sorted_apps:
            lines.append(_app_table_row(app_id, info, show_stars=True))
        lines.append(f"\n*{len(sorted_apps)} community app(s)*")
    else:
        lines.append("*No community apps yet.*")

    path = os.path.join(os.path.dirname(__file__), "COMMUNITY_APPS.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
