#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""CrossPad App Package Manager — shared core.

Platform-agnostic app management logic. Each platform repo provides
a thin wrapper that configures platform-specific settings.

Usage:
    from crosspad_app_manager import AppManager, PlatformConfig

    config = PlatformConfig(
        platform="esp-idf",
        lib_dir="components",
        official_org="CrossPad",
    )
    mgr = AppManager("/path/to/project", config)
    mgr.list_apps()
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


REMOTE_REGISTRY_REPO = "CrossPad/crosspad-apps"
REMOTE_REGISTRY_PATH = "registry.json"
LOCAL_REGISTRY_FILE = "app-registry.json"
MANIFEST_FILE = "apps.json"
CACHE_MAX_AGE_SECONDS = 3600  # 1 hour


@dataclass
class PlatformConfig:
    platform: str                      # "esp-idf", "arduino", "pc"
    lib_dir: str = "components"        # where submodules go ("components" or "lib")
    official_org: str = "CrossPad"
    lib_prefix: str = "crosspad-"      # prefix for component dirs


class AppManager:
    def __init__(self, project_dir: str, config: PlatformConfig):
        self.project_dir = Path(project_dir)
        self.config = config
        self.local_registry_path = self.project_dir / LOCAL_REGISTRY_FILE
        self.manifest_path = self.project_dir / MANIFEST_FILE

    # ── registry loading ──────────────────────────────────────────────

    def _fetch_remote_registry(self) -> dict | None:
        try:
            result = subprocess.run(
                ["gh", "api",
                 f"repos/{REMOTE_REGISTRY_REPO}/contents/{REMOTE_REGISTRY_PATH}",
                 "--jq", ".content"],
                capture_output=True, text=True, check=True, timeout=15,
            )
            import base64
            content = base64.b64decode(result.stdout.strip()).decode()
            data = json.loads(content)
            with open(self.local_registry_path, "w") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            return data
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            print(f"  Warning: Could not fetch remote registry via gh: {e}")
            return None

    def _is_cache_fresh(self) -> bool:
        if not self.local_registry_path.exists():
            return False
        age = datetime.now().timestamp() - self.local_registry_path.stat().st_mtime
        return age < CACHE_MAX_AGE_SECONDS

    def _load_registry(self) -> dict:
        if not self._is_cache_fresh():
            remote = self._fetch_remote_registry()
            if remote:
                return remote

        if self.local_registry_path.exists():
            with open(self.local_registry_path) as f:
                return json.load(f)

        print("Error: No registry available (remote unreachable, no local cache).")
        print(f"  Check your network or create {LOCAL_REGISTRY_FILE} manually.")
        sys.exit(1)

    # ── manifest ──────────────────────────────────────────────────────

    def _load_manifest(self) -> dict:
        if self.manifest_path.exists():
            with open(self.manifest_path) as f:
                return json.load(f)
        return {"installed": {}}

    def _save_manifest(self, manifest: dict):
        with open(self.manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")

    # ── git helpers ───────────────────────────────────────────────────

    def _git(self, *args, check=True, capture=False) -> subprocess.CompletedProcess:
        cmd = ["git", "-C", str(self.project_dir)] + list(args)
        if capture:
            return subprocess.run(cmd, check=check, capture_output=True, text=True)
        return subprocess.run(cmd, check=check)

    def _get_submodule_commit(self, path: str) -> str:
        result = self._git("submodule", "status", path, check=False, capture=True)
        if result.returncode == 0 and result.stdout.strip():
            line = result.stdout.strip()
            return line.lstrip(" -+").split()[0][:8]
        return "unknown"

    # ── path resolution ───────────────────────────────────────────────

    def _resolve_install_path(self, info: dict) -> str:
        """Resolve where to install the app for this platform.

        Uses the registry's component_path as a hint for the directory name,
        but replaces the prefix with the platform's lib_dir.
        """
        registry_path = info.get("component_path", "")
        # Extract the dir name (e.g. "crosspad-sampler" from "components/crosspad-sampler")
        dir_name = os.path.basename(registry_path) if registry_path else ""
        if not dir_name:
            app_id = info.get("name", "unknown").lower().replace(" ", "-")
            dir_name = f"{self.config.lib_prefix}{app_id}"
        return f"{self.config.lib_dir}/{dir_name}"

    # ── checks ────────────────────────────────────────────────────────

    def _is_compatible(self, info: dict) -> bool:
        platforms = info.get("platforms", [])
        return not platforms or self.config.platform in platforms

    def _is_official(self, info: dict) -> bool:
        repo = info.get("repo", "")
        return f"/{self.config.official_org}/" in repo

    @staticmethod
    def _format_requires(info: dict) -> str:
        requires = info.get("requires", {})
        if isinstance(requires, list):
            requires = {r: "*" for r in requires}
        parts = []
        for dep, ver in requires.items():
            short = dep.replace("crosspad-", "")
            parts.append(f"{short} {ver}" if ver != "*" else short)
        return ", ".join(parts) if parts else ""

    # ── commands ──────────────────────────────────────────────────────

    def _print_app_line(self, app_id: str, info: dict, manifest: dict):
        installed = app_id in manifest.get("installed", {})
        status_icon = "\u2713" if installed else " "
        status_text = ""
        if installed:
            inst = manifest["installed"][app_id]
            ref = inst.get("ref", "main")
            commit = inst.get("version", "")
            status_text = f"  [{ref} @ {commit}]"
        print(f"  [{status_icon}] {app_id:<16} {info['description']}{status_text}")

    def list_apps(self, show_all: bool = False):
        registry = self._load_registry()
        manifest = self._load_manifest()
        apps = registry.get("apps", {})

        if not apps:
            print("No apps available in registry.")
            return

        compatible = {k: v for k, v in apps.items() if self._is_compatible(v)}
        incompatible = {k: v for k, v in apps.items() if not self._is_compatible(v)}
        official = {k: v for k, v in compatible.items() if self._is_official(v)}
        community = {k: v for k, v in compatible.items() if not self._is_official(v)}

        print(f"\nCrossPad Apps (platform: {self.config.platform}):")
        print("-" * 75)

        if official:
            print("\n  Official:")
            for app_id, info in official.items():
                self._print_app_line(app_id, info, manifest)

        if community:
            print("\n  Community:")
            for app_id, info in community.items():
                self._print_app_line(app_id, info, manifest)

        if not official and not community:
            print("  No compatible apps found.")

        if show_all and incompatible:
            print(f"\n  Incompatible with {self.config.platform}:")
            for app_id, info in incompatible.items():
                platforms = ", ".join(info.get("platforms", []))
                req = self._format_requires(info)
                req_text = f"  [{req}]" if req else ""
                print(f"  [ ] {app_id:<16} {info['description']}  ({platforms} only){req_text}")

        print()
        installed_count = sum(1 for k in manifest.get("installed", {}) if k in compatible)
        print(f"  {installed_count}/{len(compatible)} compatible installed"
              f"  ({len(apps)} total in registry)")
        print()

    def install(self, app_name: str, ref: str = "main", origin: str = None, force: bool = False):
        registry = self._load_registry()
        manifest = self._load_manifest()
        apps = registry.get("apps", {})

        if app_name not in apps:
            print(f"Error: Unknown app '{app_name}'.")
            print(f"Available: {', '.join(apps.keys())}")
            sys.exit(1)

        if app_name in manifest.get("installed", {}):
            print(f"App '{app_name}' is already installed.")
            return

        info = apps[app_name]

        if not self._is_compatible(info) and not force:
            platforms = ", ".join(info.get("platforms", []))
            print(f"Warning: '{app_name}' is not compatible with {self.config.platform}.")
            print(f"  Supported platforms: {platforms}")
            print(f"  Use --force to install anyway.")
            return

        repo = origin if origin else info["repo"]
        install_path = self._resolve_install_path(info)

        # Check required components
        requires = info.get("requires", {})
        if isinstance(requires, list):
            requires = {r: "*" for r in requires}
        for req, ver in requires.items():
            req_path = self.project_dir / self.config.lib_dir / req
            if not req_path.exists():
                print(f"Warning: Required component '{req}' ({ver}) not found at {req_path}")

        print(f"Installing {info['name']}...")
        print(f"  Repo: {repo}")
        print(f"  Path: {install_path}")
        print(f"  Ref:  {ref}")

        try:
            self._git("submodule", "add", repo, install_path)
        except subprocess.CalledProcessError:
            print(f"Error: Failed to add submodule. Check repo URL and network.")
            sys.exit(1)

        if ref != "main":
            full_path = self.project_dir / install_path
            try:
                subprocess.run(["git", "-C", str(full_path), "fetch", "origin"], check=True)
                subprocess.run(["git", "-C", str(full_path), "checkout", ref], check=True)
                self._git("add", install_path)
            except subprocess.CalledProcessError:
                print(f"Error: Failed to checkout ref '{ref}'.")
                sys.exit(1)

        commit = self._get_submodule_commit(install_path)
        manifest.setdefault("installed", {})[app_name] = {
            "version": commit,
            "ref": ref,
            "repo": repo,
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_manifest(manifest)

        print(f"\n  {info['name']} installed successfully.")
        self._print_next_steps()

    def remove(self, app_name: str):
        manifest = self._load_manifest()
        registry = self._load_registry()
        apps = registry.get("apps", {})

        if app_name not in manifest.get("installed", {}):
            print(f"App '{app_name}' is not installed.")
            return

        info = apps.get(app_name, {})
        install_path = self._resolve_install_path(info) if info else \
            f"{self.config.lib_dir}/{self.config.lib_prefix}{app_name}"

        print(f"Removing {info.get('name', app_name)}...")

        try:
            self._git("submodule", "deinit", "-f", install_path)
            self._git("rm", "-f", install_path)
        except subprocess.CalledProcessError:
            print(f"Warning: git submodule removal had issues, cleaning up manually.")

        modules_path = self.project_dir / ".git" / "modules" / install_path
        if modules_path.exists():
            import shutil
            shutil.rmtree(modules_path)

        del manifest["installed"][app_name]
        self._save_manifest(manifest)

        print(f"\n  {info.get('name', app_name)} removed.")
        self._print_next_steps()

    def update(self, app_name: str = None, update_all: bool = False):
        manifest = self._load_manifest()
        registry = self._load_registry()
        apps = registry.get("apps", {})

        if update_all:
            targets = list(manifest.get("installed", {}).keys())
        elif app_name:
            if app_name not in manifest.get("installed", {}):
                print(f"App '{app_name}' is not installed.")
                return
            targets = [app_name]
        else:
            print("Specify an app name or --all.")
            return

        if not targets:
            print("No apps installed.")
            return

        for name in targets:
            info = apps.get(name, {})
            inst = manifest["installed"][name]
            install_path = self._resolve_install_path(info) if info else \
                f"{self.config.lib_dir}/{self.config.lib_prefix}{name}"
            ref = inst.get("ref", "main")
            full_path = self.project_dir / install_path

            if not full_path.exists():
                print(f"  {name}: path missing, skipping.")
                continue

            print(f"Updating {info.get('name', name)} ({ref})...")

            try:
                subprocess.run(["git", "-C", str(full_path), "fetch", "origin"], check=True)
                checkout_ref = f"origin/{ref}" \
                    if not ref.startswith(("origin/", "refs/")) and len(ref) < 12 \
                    else ref
                subprocess.run(["git", "-C", str(full_path), "checkout", checkout_ref], check=True)
                self._git("add", install_path)
            except subprocess.CalledProcessError:
                print(f"  Error updating {name}.")
                continue

            commit = self._get_submodule_commit(install_path)
            old_commit = inst.get("version", "?")
            inst["version"] = commit
            inst["updated_at"] = datetime.now(timezone.utc).isoformat()
            print(f"  {old_commit} -> {commit}")

        self._save_manifest(manifest)
        if targets:
            self._print_next_steps()

    def _print_next_steps(self):
        """Print platform-specific rebuild instructions."""
        if self.config.platform == "esp-idf":
            print(f"\n  Next: idf.py fullclean && idf.py build")
        elif self.config.platform == "arduino":
            print(f"\n  Next: pio run --target clean && pio run")
        else:
            print(f"\n  Next: rebuild your project")


# ── Standalone CLI ────────────────────────────────────────────────────

def cli_main(config: PlatformConfig):
    """Generic CLI entry point for any platform."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="crosspad-apps",
        description="CrossPad App Package Manager",
    )
    sub = parser.add_subparsers(dest="command")

    list_cmd = sub.add_parser("list", help="List available and installed apps")
    list_cmd.add_argument("--all", action="store_true", help="Show incompatible apps too")

    install_cmd = sub.add_parser("install", help="Install an app")
    install_cmd.add_argument("app", help="App name")
    install_cmd.add_argument("--ref", default="main", help="Branch/tag/commit")
    install_cmd.add_argument("--origin", default=None, help="Override repo URL")
    install_cmd.add_argument("--force", action="store_true", help="Install despite platform incompatibility")

    remove_cmd = sub.add_parser("remove", help="Remove an app")
    remove_cmd.add_argument("app", help="App name")

    update_cmd = sub.add_parser("update", help="Update app(s)")
    update_cmd.add_argument("app", nargs="?", help="App name")
    update_cmd.add_argument("--all", action="store_true", help="Update all")

    args = parser.parse_args()
    mgr = AppManager(os.getcwd(), config)

    if args.command == "list":
        mgr.list_apps(show_all=args.all)
    elif args.command == "install":
        mgr.install(args.app, ref=args.ref, origin=args.origin, force=args.force)
    elif args.command == "remove":
        mgr.remove(args.app)
    elif args.command == "update":
        mgr.update(app_name=args.app, update_all=args.all)
    else:
        parser.print_help()
