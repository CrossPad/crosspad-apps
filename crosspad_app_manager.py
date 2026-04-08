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
from dataclasses import dataclass
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

    # -- registry loading -----------------------------------------------------

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
        except (subprocess.CalledProcessError, FileNotFoundError,
                subprocess.TimeoutExpired) as e:
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

    # -- manifest -------------------------------------------------------------

    def _load_manifest(self) -> dict:
        if self.manifest_path.exists():
            with open(self.manifest_path) as f:
                return json.load(f)
        return {"installed": {}}

    def _save_manifest(self, manifest: dict):
        with open(self.manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")

    # -- git helpers ----------------------------------------------------------

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

    def _get_default_branch(self, path: str) -> str:
        """Detect the default branch of a submodule (main or master)."""
        full_path = self.project_dir / path
        result = subprocess.run(
            ["git", "-C", str(full_path), "remote", "show", "origin"],
            capture_output=True, text=True, check=False, timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "HEAD branch" in line:
                    return line.split(":")[-1].strip()
        for branch in ["main", "master"]:
            r = subprocess.run(
                ["git", "-C", str(full_path), "rev-parse", "--verify",
                 f"origin/{branch}"],
                capture_output=True, check=False,
            )
            if r.returncode == 0:
                return branch
        return "main"

    # -- path resolution ------------------------------------------------------

    def _resolve_install_path(self, info: dict) -> str:
        registry_path = info.get("component_path", "")
        dir_name = os.path.basename(registry_path) if registry_path else ""
        if not dir_name:
            app_id = info.get("name", "unknown").lower().replace(" ", "-")
            dir_name = f"{self.config.lib_prefix}{app_id}"
        return f"{self.config.lib_dir}/{dir_name}"

    # -- checks ---------------------------------------------------------------

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

    # -- extended helpers (for TUI) -------------------------------------------

    def get_cache_age(self) -> int:
        """Return cache age in seconds, or -1 if no cache."""
        if not self.local_registry_path.exists():
            return -1
        return int(datetime.now().timestamp()
                   - self.local_registry_path.stat().st_mtime)

    def get_submodule_dirty(self, path: str) -> bool:
        """Check if a submodule has uncommitted changes."""
        full = self.project_dir / path
        if not full.exists():
            return False
        r = subprocess.run(
            ["git", "-C", str(full), "status", "--porcelain"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        return bool(r.stdout.strip())

    def get_app_disk_usage(self, path: str) -> int:
        """Get disk usage of an app directory in bytes."""
        full = self.project_dir / path
        if not full.exists():
            return 0
        total = 0
        for dirpath, _, filenames in os.walk(full):
            for f in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
        return total

    def get_app_git_log(self, path: str, count: int = 5) -> list[str]:
        """Get recent git log for an app submodule."""
        full = self.project_dir / path
        if not full.exists():
            return []
        r = subprocess.run(
            ["git", "-C", str(full), "log", "--oneline", f"-{count}"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        return r.stdout.strip().splitlines() if r.returncode == 0 else []

    def fetch_app_changelog(self, app_id: str, registry: dict = None) -> list[str]:
        """Fetch changelog from app's crosspad-app.json via GitHub API."""
        if registry is None:
            registry = self._load_registry()
        info = registry.get("apps", {}).get(app_id, {})
        repo = info.get("repo", "")
        if not repo:
            return []
        parts = repo.rstrip("/").rstrip(".git").split("/")
        if len(parts) < 2:
            return []
        owner_repo = f"{parts[-2]}/{parts[-1]}"
        try:
            import base64
            r = subprocess.run(
                ["gh", "api",
                 f"repos/{owner_repo}/contents/crosspad-app.json",
                 "--jq", ".content"],
                capture_output=True, text=True, check=True, timeout=10,
            )
            data = json.loads(base64.b64decode(r.stdout.strip()).decode())
            return data.get("changelog", [])
        except Exception:
            return []

    def detect_serial_port(self) -> str:
        """Try to auto-detect CrossPad serial port."""
        import glob as _glob
        for pattern in ["/dev/ttyACM*", "/dev/ttyUSB*", "/dev/cu.usbmodem*"]:
            matches = _glob.glob(pattern)
            if matches:
                return matches[0]
        # Windows COM ports
        if sys.platform == "win32":
            for i in range(1, 20):
                port = f"COM{i}"
                try:
                    import serial
                    s = serial.Serial(port)
                    s.close()
                    return port
                except Exception:
                    continue
        return ""

    def _find_idf_path(self) -> str:
        """Find ESP-IDF installation path."""
        # 1. Environment variable
        p = os.environ.get("IDF_PATH", "")
        if p and os.path.isdir(p):
            return p
        # 2. VSCode settings (idf.espIdfPath)
        vscode_settings = self.project_dir / ".vscode" / "settings.json"
        if vscode_settings.exists():
            try:
                with open(vscode_settings) as f:
                    data = json.load(f)
                p = data.get("idf.espIdfPath", "")
                if p and os.path.isdir(p):
                    return p
            except (json.JSONDecodeError, OSError):
                pass
        # 3. Common locations
        for candidate in [
            Path.home() / "esp" / "esp-idf",
            Path.home() / "esp" / "v5.5" / "esp-idf",
            Path("/opt/esp-idf"),
        ]:
            if candidate.is_dir():
                return str(candidate)
        return ""

    def run_command(self, cmd: str) -> int:
        """Run a shell command in the project dir, return exit code."""
        if self.config.platform == "esp-idf":
            idf_path = self._find_idf_path()
            if idf_path:
                # Source export.sh — puts idf.py + toolchain on PATH
                export_sh = os.path.join(idf_path, "export.sh")
                if os.path.exists(export_sh):
                    cmd = (f"export IDF_PATH={idf_path} "
                           f"IDF_PATH_FORCE=1 && "
                           f". {export_sh} > /dev/null 2>&1 && {cmd}")
        sys.stdout.write(f"\n  Running: {cmd}\n\n")
        sys.stdout.flush()
        _restore_terminal()
        proc = subprocess.Popen(
            cmd, shell=True, cwd=str(self.project_dir),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=0,
        )
        while True:
            chunk = proc.stdout.read(256)
            if not chunk:
                break
            os.write(sys.stdout.fileno(), chunk)
        rc = proc.wait()
        if rc != 0:
            sys.stdout.write(f"\n  \033[1;31mFailed (exit code {rc})\033[0m\n")
        sys.stdout.flush()
        return rc

    def check_gh_auth(self) -> tuple[bool, str]:
        """Check if gh CLI is authenticated. Returns (ok, username)."""
        try:
            r = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True, text=True, check=False, timeout=5,
            )
            if r.returncode == 0:
                for line in (r.stdout + r.stderr).splitlines():
                    if "Logged in" in line or "account" in line:
                        parts = line.strip().split()
                        for p in parts:
                            if not p.startswith(("-", "~", "/", "(")):
                                if len(p) > 2 and p[0].isalpha():
                                    return True, p
                return True, "authenticated"
            return False, ""
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False, ""

    def get_all_submodules(self) -> list[dict]:
        """Get status of all git submodules."""
        result = self._git("submodule", "status", check=False, capture=True)
        subs = []
        if result.returncode != 0 or not result.stdout.strip():
            return subs
        for line in result.stdout.strip().splitlines():
            raw = line.strip()
            modified = raw.startswith("+")
            uninitialized = raw.startswith("-")
            parts = raw.lstrip(" -+").split()
            if len(parts) >= 2:
                commit = parts[0][:7]
                path = parts[1]
                name = os.path.basename(path)
                infra = name in ("crosspad-core", "crosspad-gui",
                                 "crosspad-platform-idf")
                is_app = name.startswith("crosspad-") and not infra
                subs.append({
                    "name": name, "path": path, "commit": commit,
                    "modified": modified, "uninitialized": uninitialized,
                    "infra": infra, "is_app": is_app,
                })
        return subs

    def get_build_info(self) -> dict:
        """Get firmware build status. Returns dict with binary info."""
        # Platform-specific binary paths
        if self.config.platform == "esp-idf":
            candidates = [
                self.project_dir / "build" / "CrossPad.bin",
                # fallback: find any .bin in build/
            ]
        elif self.config.platform == "arduino":
            candidates = [
                self.project_dir / ".pio" / "build" / "esp32s3" / "firmware.bin",
            ]
        else:
            return {"exists": False}

        binary = None
        for c in candidates:
            if c.exists():
                binary = c
                break

        if not binary:
            return {"exists": False}

        stat = binary.stat()
        build_time = stat.st_mtime
        size = stat.st_size

        # Check if any source files are newer than the binary
        stale = False
        newest_src = 0
        src_dirs = ["main", "components"]
        src_exts = {".c", ".cpp", ".h", ".hpp", ".cmake"}
        for src_dir in src_dirs:
            full_dir = self.project_dir / src_dir
            if not full_dir.exists():
                continue
            for dirpath, _, filenames in os.walk(full_dir):
                for fn in filenames:
                    if any(fn.endswith(ext) for ext in src_exts):
                        try:
                            mt = os.path.getmtime(os.path.join(dirpath, fn))
                            if mt > newest_src:
                                newest_src = mt
                        except OSError:
                            pass

        stale = newest_src > build_time if newest_src > 0 else False

        return {
            "exists": True,
            "path": str(binary),
            "size": size,
            "build_time": build_time,
            "stale": stale,
            "age_seconds": int(datetime.now().timestamp() - build_time),
        }

    # -- commands -------------------------------------------------------------

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
        incompatible = {k: v for k, v in apps.items()
                        if not self._is_compatible(v)}
        official = {k: v for k, v in compatible.items() if self._is_official(v)}
        community = {k: v for k, v in compatible.items()
                     if not self._is_official(v)}

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
                print(f"  [ ] {app_id:<16} {info['description']}"
                      f"  ({platforms} only){req_text}")

        print()
        installed_count = sum(1 for k in manifest.get("installed", {})
                              if k in compatible)
        print(f"  {installed_count}/{len(compatible)} compatible installed"
              f"  ({len(apps)} total in registry)")
        print()

    def install(self, app_name: str, ref: str = "main",
                origin: str = None, force: bool = False):
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
            print(f"Warning: '{app_name}' is not compatible "
                  f"with {self.config.platform}.")
            print(f"  Supported platforms: {platforms}")
            print(f"  Use --force to install anyway.")
            return

        repo = origin if origin else info["repo"]
        install_path = self._resolve_install_path(info)

        requires = info.get("requires", {})
        if isinstance(requires, list):
            requires = {r: "*" for r in requires}
        for req, ver in requires.items():
            req_path = self.project_dir / self.config.lib_dir / req
            if not req_path.exists():
                print(f"Warning: Required component '{req}' ({ver}) "
                      f"not found at {req_path}")

        print(f"Installing {info['name']}...")
        print(f"  Repo: {repo}")
        print(f"  Path: {install_path}")
        print(f"  Ref:  {ref}")

        full_path = self.project_dir / install_path
        already_exists = full_path.exists() and (full_path / ".git").exists()

        if already_exists:
            print(f"  Submodule already exists at {install_path}, "
                  "registering in manifest.")
        else:
            try:
                self._git("submodule", "add", repo, install_path)
            except subprocess.CalledProcessError:
                print("Error: Failed to add submodule. "
                      "Check repo URL and network.")
                sys.exit(1)

        if ref != "main":
            try:
                subprocess.run(
                    ["git", "-C", str(full_path), "fetch", "origin"],
                    check=True)
                subprocess.run(
                    ["git", "-C", str(full_path), "checkout", ref],
                    check=True)
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
        install_path = (self._resolve_install_path(info) if info else
                        f"{self.config.lib_dir}/{self.config.lib_prefix}"
                        f"{app_name}")

        print(f"Removing {info.get('name', app_name)}...")

        try:
            self._git("submodule", "deinit", "-f", install_path)
            self._git("rm", "-f", install_path)
        except subprocess.CalledProcessError:
            print("Warning: git submodule removal had issues, "
                  "cleaning up manually.")

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
            install_path = (self._resolve_install_path(info) if info else
                            f"{self.config.lib_dir}/{self.config.lib_prefix}"
                            f"{name}")
            ref = inst.get("ref", "main")
            full_path = self.project_dir / install_path

            if not full_path.exists():
                print(f"  {name}: path missing, skipping.")
                continue

            print(f"Updating {info.get('name', name)} ({ref})...")

            try:
                subprocess.run(
                    ["git", "-C", str(full_path), "fetch", "origin"],
                    check=True)
                checkout_ref = (f"origin/{ref}"
                                if not ref.startswith(("origin/", "refs/"))
                                and len(ref) < 12
                                else ref)
                subprocess.run(
                    ["git", "-C", str(full_path), "checkout", checkout_ref],
                    check=True)
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

    def sync(self):
        """Detect existing app submodules and sync manifest."""
        registry = self._load_registry()
        manifest = self._load_manifest()
        apps = registry.get("apps", {})

        synced = 0
        for app_id, info in apps.items():
            install_path = self._resolve_install_path(info)
            full_path = self.project_dir / install_path

            already_in_manifest = app_id in manifest.get("installed", {})
            exists_on_disk = (full_path.exists()
                              and (full_path / ".git").exists())

            if exists_on_disk and not already_in_manifest:
                commit = self._get_submodule_commit(install_path)
                ref = self._get_default_branch(install_path)
                manifest.setdefault("installed", {})[app_id] = {
                    "version": commit,
                    "ref": ref,
                    "repo": info.get("repo", ""),
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                }
                print(f"  + {app_id} ({install_path} @ {commit}, ref={ref})")
                synced += 1
            elif not exists_on_disk and already_in_manifest:
                del manifest["installed"][app_id]
                print(f"  - {app_id} (removed from manifest, not on disk)")
                synced += 1

        if synced:
            self._save_manifest(manifest)
            print(f"\nSynced {synced} app(s).")
        else:
            print("Manifest is up to date.")

    def _print_next_steps(self):
        if self.config.platform == "esp-idf":
            print(f"\n  Next: idf.py fullclean && idf.py build")
        elif self.config.platform == "arduino":
            print(f"\n  Next: pio run --target clean && pio run")
        else:
            print(f"\n  Next: rebuild your project")


# == Standalone CLI ===========================================================

def cli_main(config: PlatformConfig):
    """Generic CLI entry point for any platform."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="crosspad-apps",
        description="CrossPad App Package Manager",
    )
    sub = parser.add_subparsers(dest="command")

    list_cmd = sub.add_parser("list", help="List available and installed apps")
    list_cmd.add_argument("--all", action="store_true",
                          help="Show incompatible apps too")

    install_cmd = sub.add_parser("install", help="Install an app")
    install_cmd.add_argument("app", help="App name")
    install_cmd.add_argument("--ref", default="main",
                             help="Branch/tag/commit")
    install_cmd.add_argument("--origin", default=None,
                             help="Override repo URL")
    install_cmd.add_argument("--force", action="store_true",
                             help="Install despite platform incompatibility")

    remove_cmd = sub.add_parser("remove", help="Remove an app")
    remove_cmd.add_argument("app", help="App name")

    update_cmd = sub.add_parser("update", help="Update app(s)")
    update_cmd.add_argument("app", nargs="?", help="App name")
    update_cmd.add_argument("--all", action="store_true", help="Update all")

    sub.add_parser("sync", help="Sync manifest with existing submodules")
    sub.add_parser("tui", help="Interactive terminal UI")

    args = parser.parse_args()
    mgr = AppManager(os.getcwd(), config)

    if args.command == "list":
        mgr.list_apps(show_all=args.all)
    elif args.command == "install":
        mgr.install(args.app, ref=args.ref, origin=args.origin,
                    force=args.force)
    elif args.command == "remove":
        mgr.remove(args.app)
    elif args.command == "update":
        mgr.update(app_name=args.app, update_all=args.all)
    elif args.command == "sync":
        mgr.sync()
    elif args.command == "tui" or args.command is None:
        if _is_interactive():
            tui_main(config)
        elif args.command is None:
            parser.print_help()
        else:
            print("Error: TUI requires an interactive terminal.")
            sys.exit(1)
    else:
        parser.print_help()


# =============================================================================
#  Interactive TUI
# =============================================================================

def _is_interactive():
    """Check if stdin is a real terminal."""
    try:
        return os.isatty(sys.stdin.fileno())
    except (OSError, AttributeError):
        return False


# -- ANSI helpers -------------------------------------------------------------

class _C:
    """ANSI escape codes."""
    RST = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UL = "\033[4m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"

    BRED = "\033[1;31m"
    BGREEN = "\033[1;32m"
    BYELLOW = "\033[1;33m"
    BBLUE = "\033[1;34m"
    BMAGENTA = "\033[1;35m"
    BCYAN = "\033[1;36m"
    BWHITE = "\033[1;37m"

    BGBLUE = "\033[44m"
    BGCYAN = "\033[46m"


def _w(s: str):
    """Write to stdout without newline."""
    sys.stdout.write(s)
    sys.stdout.flush()


def _get_size() -> tuple[int, int]:
    """Return (columns, rows) of terminal."""
    try:
        import shutil as _sh
        return _sh.get_terminal_size((80, 24))
    except Exception:
        return (80, 24)


def _clear():
    _w("\033[2J\033[H")


def _hide_cursor():
    _w("\033[?25l")


def _show_cursor():
    _w("\033[?25h")


# Terminal state management — raw mode breaks subprocess output
_saved_termios = None


def _save_terminal():
    """Save terminal attributes before entering TUI."""
    global _saved_termios
    try:
        import termios
        _saved_termios = termios.tcgetattr(sys.stdin.fileno())
    except (ImportError, OSError):
        pass


def _restore_terminal():
    """Restore terminal to normal (cooked) mode for subprocess output."""
    if _saved_termios is not None:
        try:
            import termios
            termios.tcsetattr(sys.stdin.fileno(),
                              termios.TCSADRAIN, _saved_termios)
        except (ImportError, OSError):
            pass
    _show_cursor()


def _read_key() -> str:
    """Read a single keypress, return normalized key name."""
    try:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[A": return "up"
                if seq == "[B": return "down"
                if seq == "[C": return "right"
                if seq == "[D": return "left"
                if seq == "[5":
                    sys.stdin.read(1)
                    return "pgup"
                if seq == "[6":
                    sys.stdin.read(1)
                    return "pgdn"
                if seq == "[H": return "home"
                if seq == "[F": return "end"
                return "esc"
            if ch in ("\r", "\n"): return "enter"
            if ch in ("\x7f", "\x08"): return "backspace"
            if ch == "\t": return "tab"
            if ch == "\x03": return "ctrl-c"
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except (ImportError, OSError):
        import msvcrt
        ch = msvcrt.getch()
        if ch in (b"\xe0", b"\x00"):
            ch2 = msvcrt.getch()
            m = {b"H": "up", b"P": "down", b"K": "left", b"M": "right",
                 b"I": "pgup", b"Q": "pgdn", b"G": "home", b"O": "end"}
            return m.get(ch2, "")
        if ch == b"\r": return "enter"
        if ch == b"\x1b": return "esc"
        if ch == b"\x08": return "backspace"
        if ch == b"\t": return "tab"
        if ch == b"\x03": return "ctrl-c"
        return ch.decode("utf-8", errors="ignore")


# -- TUI widgets --------------------------------------------------------------

def _confirm(prompt: str) -> bool:
    """Yes/no prompt. Returns True on 'y'."""
    _w(f"\n  {prompt} {_C.DIM}[y/N]{_C.RST} ")
    _show_cursor()
    while True:
        key = _read_key()
        if key in ("y", "Y"):
            _w(f"{_C.BGREEN}yes{_C.RST}\n")
            _hide_cursor()
            return True
        if key in ("n", "N", "enter", "esc", "ctrl-c"):
            _w(f"{_C.GRAY}no{_C.RST}\n")
            _hide_cursor()
            return False


def _text_input(prompt: str, default: str = "") -> str | None:
    """Single-line text input. Returns None on cancel."""
    buf = list(default)
    _show_cursor()
    while True:
        _w(f"\r\033[K  {prompt}: {_C.BWHITE}{''.join(buf)}{_C.RST}\033[K")
        key = _read_key()
        if key == "enter":
            _w("\n")
            _hide_cursor()
            return "".join(buf)
        elif key in ("esc", "ctrl-c"):
            _w("\n")
            _hide_cursor()
            return None
        elif key == "backspace":
            if buf:
                buf.pop()
        elif len(key) == 1 and key.isprintable():
            buf.append(key)


def _menu_select(title: str, items: list[str],
                 descriptions: list[str] = None,
                 hotkeys: list[str] = None) -> int:
    """Arrow-key menu. Returns selected index or -1."""
    cursor = 0
    while True:
        _clear()
        _w(f"\n  {_C.BCYAN}{title}{_C.RST}\n")
        _w(f"  {_C.GRAY}{'─' * (_get_size()[0] - 4)}{_C.RST}\n\n")
        for i, item in enumerate(items):
            if i == cursor:
                _w(f"  {_C.BYELLOW}> {item}{_C.RST}\n")
                if descriptions and i < len(descriptions) and descriptions[i]:
                    _w(f"    {_C.GRAY}{descriptions[i]}{_C.RST}\n")
            else:
                _w(f"    {item}\n")
        _w(f"\n  {_C.GRAY}[arrows] navigate  "
           f"[enter] select  [q/esc] back{_C.RST}\n")
        key = _read_key()
        if key == "up":
            cursor = (cursor - 1) % len(items)
        elif key == "down":
            cursor = (cursor + 1) % len(items)
        elif key == "enter":
            return cursor
        elif key in ("esc", "ctrl-c"):
            return -1
        elif key == "q":
            return -1
        elif hotkeys:
            for hi, hk in enumerate(hotkeys):
                if hk and key == hk:
                    return hi


def _pause():
    _w(f"\n  {_C.GRAY}Press any key to continue...{_C.RST}")
    _read_key()


# -- Main TUI class -----------------------------------------------------------

class _TUI:
    """Interactive TUI for CrossPad App Manager."""

    def __init__(self, config: PlatformConfig):
        self.config = config
        self.mgr = AppManager(os.getcwd(), config)
        self._serial_port = ""
        self._reload()

    def _reload(self):
        """(Re)load registry and manifest."""
        self._registry = self.mgr._load_registry()
        self._manifest = self.mgr._load_manifest()
        self._apps = self._registry.get("apps", {})
        self._installed = self._manifest.get("installed", {})

    @property
    def _cols(self):
        return _get_size()[0]

    def run(self):
        _save_terminal()
        _hide_cursor()
        try:
            self._dashboard()
        except KeyboardInterrupt:
            pass
        finally:
            _restore_terminal()
            _clear()

    # -- formatting -----------------------------------------------------------

    @staticmethod
    def _fmt_age(seconds: int) -> str:
        if seconds < 0:
            return "never"
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        return f"{seconds // 86400}d ago"

    @staticmethod
    def _fmt_size(n: int) -> str:
        for u in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
            n /= 1024
        return f"{n:.1f} TB"

    @staticmethod
    def _fmt_platforms(platforms: list) -> str:
        return " \u00b7 ".join(platforms) if platforms else "all"

    def _categorize(self) -> dict:
        """Group apps by category, ordered."""
        cats: dict[str, list] = {}
        for app_id, info in self._apps.items():
            cat = info.get("category", "other")
            cats.setdefault(cat, []).append((app_id, info))
        order = ["music", "audio", "tools", "other"]
        result = {}
        for k in order:
            if k in cats:
                result[k] = cats[k]
        for k, v in cats.items():
            if k not in order:
                result[k] = v
        return result

    def _compatible_count(self) -> tuple[int, int]:
        """(installed_compatible, total_compatible)."""
        compat = [k for k, v in self._apps.items()
                  if self.mgr._is_compatible(v)]
        inst = [k for k in compat if k in self._installed]
        return len(inst), len(compat)

    # -- rendering helpers ----------------------------------------------------

    def _header(self, title: str, right: str = ""):
        w = self._cols
        _w(f"\n  {_C.BCYAN}{title}{_C.RST}")
        if right:
            pad = w - 4 - len(title) - len(right)
            _w(f"{' ' * max(pad, 2)}{_C.GRAY}{right}{_C.RST}")
        _w(f"\n  {_C.GRAY}{'─' * (w - 4)}{_C.RST}\n")

    def _section(self, title: str):
        w = self._cols
        pad = w - 6 - len(title)
        _w(f"\n  {_C.GRAY}── {_C.BWHITE}{title} "
           f"{_C.GRAY}{'─' * max(pad, 2)}{_C.RST}\n")

    def _footer(self, hints: str):
        _w(f"\n  {_C.GRAY}{hints}{_C.RST}\n")

    def _open_url(self, url: str):
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", url],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            elif sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", url],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            else:
                os.startfile(url)
        except OSError:
            pass

    # -- Dashboard ------------------------------------------------------------

    def _dashboard(self):
        while True:
            _clear()
            w = self._cols
            plat = self.config.platform

            # -- title box --
            inner = f"CrossPad App Manager   \u00b7   {plat}"
            box_w = max(len(inner) + 6, 50)
            if box_w > w - 4:
                box_w = w - 4
            pad_total = box_w - len(inner)
            lp = pad_total // 2
            rp = pad_total - lp

            _w(f"\n  {_C.BCYAN}\u256d{'─' * box_w}\u256e{_C.RST}\n")
            _w(f"  {_C.BCYAN}\u2502{_C.RST}"
               f"{' ' * lp}{_C.BWHITE}CrossPad App Manager{_C.RST}"
               f"   {_C.GRAY}\u00b7{_C.RST}   "
               f"{_C.BCYAN}{plat}{_C.RST}"
               f"{' ' * rp}{_C.BCYAN}\u2502{_C.RST}\n")
            _w(f"  {_C.BCYAN}\u2570{'─' * box_w}\u256f{_C.RST}\n")

            # -- stats --
            inst_c, total_c = self._compatible_count()
            cache_age = self.mgr.get_cache_age()
            cache_str = self._fmt_age(cache_age) if cache_age >= 0 else "none"
            proj = self.mgr.project_dir.name
            plat_label = plat.upper().replace("-", " ")

            _w(f"\n   {_C.GRAY}Platform{_C.RST}    "
               f"{_C.BWHITE}{plat_label}{_C.RST}")
            _w(f"{'':>10}{_C.GRAY}Project{_C.RST}    "
               f"{_C.BWHITE}{proj}{_C.RST}\n")
            _w(f"   {_C.GRAY}Installed{_C.RST}   "
               f"{_C.BWHITE}{inst_c}{_C.RST}"
               f"{_C.GRAY}/{total_c} compatible{_C.RST}")
            _w(f"{'':>4}{_C.GRAY}Registry{_C.RST}   "
               f"{_C.BWHITE}{cache_str}{_C.RST}\n")

            # -- installed apps --
            if self._installed:
                self._section("Installed Apps")
                for app_id, inst in self._installed.items():
                    info = self._apps.get(app_id, {})
                    ver = info.get("version", "?")
                    name = info.get("name", app_id)
                    ref = inst.get("ref", "?")
                    commit = inst.get("version", "?")
                    cat = info.get("category", "")
                    _w(f"   {_C.BGREEN}\u25cf{_C.RST} "
                       f"{name:<18} "
                       f"{_C.GRAY}v{ver:<8}{_C.RST} "
                       f"{_C.DIM}{ref} @ {commit}{_C.RST}   "
                       f"{_C.DIM}{cat}{_C.RST}\n")
            else:
                _w(f"\n   {_C.GRAY}No apps installed yet. "
                   f"Press {_C.BYELLOW}b{_C.RST}{_C.GRAY} to browse."
                   f"{_C.RST}\n")

            # -- quick actions --
            self._section("Quick Actions")
            acts = [
                ("B", "Browse & Install"),
                ("U", "Update All"),
                ("H", "Health Check"),
            ]
            acts2 = [
                ("F", "Build & Flash"),
                ("O", "OTA Flash"),
                ("T", "Dev Tools"),
                ("Q", "Quit"),
            ]
            row1 = "   "
            for key, label in acts:
                row1 += (f"{_C.BCYAN}[{key}]{_C.RST} {label}    ")
            _w(row1 + "\n")
            row2 = "   "
            for key, label in acts2:
                row2 += (f"{_C.BCYAN}[{key}]{_C.RST} {label}    ")
            _w(row2 + "\n")

            key = _read_key()
            if key in ("q", "ctrl-c", "esc"):
                break
            elif key == "b":
                self._browse()
                self._reload()
            elif key == "u":
                self._update_flow()
                self._reload()
            elif key == "h":
                self._health()
            elif key == "f":
                self._build_flash()
            elif key == "o":
                self._quick_ota()
            elif key == "t":
                self._dev_tools()
                self._reload()

    # -- Browse ---------------------------------------------------------------

    def _build_browse_list(self):
        """Build flat list: [(type, data), ...] for browse view."""
        cats = self._categorize()
        items = []
        for cat, app_list in cats.items():
            items.append(("cat", cat))
            for app_id, info in sorted(app_list, key=lambda x: x[0]):
                items.append(("app", (app_id, info)))
        selectable = [i for i, (t, _) in enumerate(items) if t == "app"]
        return items, selectable

    def _browse(self):
        items, selectable = self._build_browse_list()
        if not selectable:
            _clear()
            _w(f"\n  {_C.GRAY}No apps in registry.{_C.RST}\n")
            _read_key()
            return

        cursor = 0
        search = ""
        search_mode = False
        scroll_offset = 0

        while True:
            _clear()
            w = self._cols
            _, rows = _get_size()

            self._header("Browse Apps",
                          f"{'/' if not search_mode else ''} search   "
                          f"{len(self._apps)} apps")

            # search bar
            if search_mode:
                _w(f"  {_C.BYELLOW}/{_C.RST} "
                   f"{_C.BWHITE}{search}{_C.RST}\u2588\n")

            # filter
            if search:
                q = search.lower()
                filtered = [i for i in selectable
                            if q in items[i][1][0].lower()
                            or q in items[i][1][1].get("name", "").lower()
                            or q in items[i][1][1].get("description", ""
                                                       ).lower()
                            or q in items[i][1][1].get("category", "").lower()]
            else:
                filtered = selectable[:]

            if not filtered:
                _w(f"\n  {_C.GRAY}No matches for '{search}'.{_C.RST}\n")
            else:
                if cursor >= len(filtered):
                    cursor = len(filtered) - 1
                if cursor < 0:
                    cursor = 0

                # visible area (leave room for header+footer)
                max_visible = max(rows - 12, 5)
                if cursor < scroll_offset:
                    scroll_offset = cursor
                if cursor >= scroll_offset + max_visible:
                    scroll_offset = cursor - max_visible + 1

                last_cat = None
                shown = 0
                for sel_idx in range(len(filtered)):
                    if sel_idx < scroll_offset:
                        continue
                    if shown >= max_visible:
                        break

                    item_idx = filtered[sel_idx]
                    # find category
                    for ci in range(item_idx - 1, -1, -1):
                        if items[ci][0] == "cat":
                            cat_name = items[ci][1]
                            if cat_name != last_cat:
                                self._section(cat_name)
                                last_cat = cat_name
                            break

                    app_id, info = items[item_idx][1]
                    selected = sel_idx == cursor
                    is_inst = app_id in self._installed
                    compat = self.mgr._is_compatible(info)
                    name = info.get("name", app_id)
                    ver = info.get("version", "?")
                    desc = info.get("description", "")

                    max_desc = w - 42
                    if max_desc > 0 and len(desc) > max_desc:
                        desc = desc[:max_desc - 3] + "..."

                    icon = (f"{_C.BGREEN}\u25cf{_C.RST}" if is_inst
                            else f"{_C.GRAY}\u25cb{_C.RST}")

                    if selected:
                        mk = f"{_C.BYELLOW}>{_C.RST}"
                        nc = f"{_C.BWHITE}{name}{_C.RST}"
                    else:
                        mk = " "
                        nc = (f"{_C.RST}{name}{_C.RST}" if compat
                              else f"{_C.DIM}{name}{_C.RST}")

                    vc = f"{_C.GRAY}v{ver}{_C.RST}"
                    dc = (f"{_C.GRAY}{desc}{_C.RST}" if compat
                          else f"{_C.DIM}{desc}{_C.RST}")

                    tags = ""
                    if is_inst:
                        tags += f"  {_C.GREEN}installed{_C.RST}"
                    elif not compat:
                        plats = ", ".join(info.get("platforms", []))
                        tags += f"  {_C.RED}{plats}{_C.RST}"

                    _w(f"  {mk} {icon} {nc:<20} {vc:<10} {dc}{tags}\n")
                    shown += 1

                # scroll indicator
                if len(filtered) > max_visible:
                    pos = scroll_offset + max_visible
                    _w(f"\n  {_C.DIM}"
                       f"  [{cursor + 1}/{len(filtered)}]{_C.RST}")

            if search_mode:
                self._footer("type to filter   enter confirm   esc cancel")
            else:
                self._footer(
                    "\u2191\u2193 navigate   enter detail   "
                    "i install   r remove   / search   q back"
                )

            key = _read_key()

            # -- search mode input --
            if search_mode:
                if key == "enter":
                    search_mode = False
                elif key in ("esc", "ctrl-c"):
                    search = ""
                    search_mode = False
                    cursor = 0
                elif key == "backspace":
                    search = search[:-1]
                    cursor = 0
                elif len(key) == 1 and key.isprintable():
                    search += key
                    cursor = 0
                continue

            # -- normal navigation --
            if key == "up":
                cursor = ((cursor - 1) % len(filtered)
                          if filtered else 0)
            elif key == "down":
                cursor = ((cursor + 1) % len(filtered)
                          if filtered else 0)
            elif key == "pgup":
                cursor = max(0, cursor - 10)
            elif key == "pgdn":
                cursor = min(len(filtered) - 1, cursor + 10) if filtered else 0
            elif key == "home":
                cursor = 0
            elif key == "end":
                cursor = len(filtered) - 1 if filtered else 0
            elif key == "/":
                search_mode = True
            elif key == "enter" and filtered:
                app_id = items[filtered[cursor]][1][0]
                self._app_detail(app_id)
                self._reload()
                items, selectable = self._build_browse_list()
                # re-filter
            elif key == "i" and filtered:
                app_id = items[filtered[cursor]][1][0]
                if app_id not in self._installed:
                    self._install_flow(app_id)
                    self._reload()
                    items, selectable = self._build_browse_list()
            elif key == "r" and filtered:
                app_id = items[filtered[cursor]][1][0]
                if app_id in self._installed:
                    self._remove_flow(app_id)
                    self._reload()
                    items, selectable = self._build_browse_list()
            elif key in ("q", "esc"):
                break

    # -- App Detail -----------------------------------------------------------

    def _app_detail(self, app_id: str):
        info = self._apps.get(app_id, {})
        while True:
            _clear()
            self._reload()
            is_inst = app_id in self._installed
            name = info.get("name", app_id)
            ver = info.get("version", "?")
            desc = info.get("description", "")
            cat = info.get("category", "other")
            platforms = info.get("platforms", [])
            repo = info.get("repo", "")
            w = self._cols

            # -- title --
            icon = (f"{_C.BGREEN}\u25c6{_C.RST}" if is_inst
                    else f"{_C.BCYAN}\u25c7{_C.RST}")
            ver_str = f"v{ver}"
            pad = max(w - len(name) - len(ver_str) - 6, 2)
            _w(f"\n  {icon} {_C.BWHITE}{name}{_C.RST}"
               f"{' ' * pad}{_C.GRAY}{ver_str}{_C.RST}\n")
            _w(f"  {_C.GRAY}{'─' * (w - 4)}{_C.RST}\n\n")
            _w(f"  {desc}\n\n")

            # -- info table --
            _w(f"   {_C.GRAY}Category{_C.RST}     {cat}\n")
            _w(f"   {_C.GRAY}Platforms{_C.RST}    "
               f"{self._fmt_platforms(platforms)}\n")

            req_str = self.mgr._format_requires(info)
            if req_str:
                _w(f"   {_C.GRAY}Requires{_C.RST}     {req_str}\n")

            if repo:
                short = repo.replace("https://github.com/", "").rstrip(".git")
                _w(f"   {_C.GRAY}Repo{_C.RST}         "
                   f"{_C.CYAN}{short}{_C.RST}\n")

            if is_inst:
                install_path = self.mgr._resolve_install_path(info)
                size = self.mgr.get_app_disk_usage(install_path)
                if size > 0:
                    _w(f"   {_C.GRAY}Size{_C.RST}         "
                       f"{self._fmt_size(size)}\n")

            # -- status --
            self._section("Status")
            if is_inst:
                inst = self._installed[app_id]
                ref = inst.get("ref", "?")
                commit = inst.get("version", "?")
                date = inst.get("installed_at", "?")[:10]
                updated = inst.get("updated_at", "")
                _w(f"   {_C.BGREEN}\u25cf Installed{_C.RST}   "
                   f"{ref} @ {commit}   "
                   f"{_C.GRAY}since {date}{_C.RST}\n")
                if updated:
                    _w(f"   {_C.GRAY}Updated{_C.RST}      "
                       f"{updated[:10]}\n")

                install_path = self.mgr._resolve_install_path(info)
                dirty = self.mgr.get_submodule_dirty(install_path)
                if dirty:
                    _w(f"   {_C.BYELLOW}\u26a0 "
                       f"Uncommitted changes{_C.RST}\n")

                # recent commits
                commits = self.mgr.get_app_git_log(install_path, 5)
                if commits:
                    self._section("Recent Commits")
                    for c in commits:
                        _w(f"   {_C.GRAY}{c}{_C.RST}\n")
            else:
                compat = self.mgr._is_compatible(info)
                if compat:
                    _w(f"   {_C.GRAY}\u25cb Not installed{_C.RST}\n")
                else:
                    plats = ", ".join(platforms)
                    _w(f"   {_C.RED}\u2717 Not compatible{_C.RST} "
                       f"{_C.GRAY}({plats} only){_C.RST}\n")

            # -- actions --
            _w("\n")
            acts = []
            if is_inst:
                acts.append("[u] Update")
                acts.append("[r] Remove")
            else:
                acts.append("[i] Install")
            acts.append("[o] Open repo")
            acts.append("[l] Changelog")
            acts.append("q back")
            self._footer("   ".join(acts))

            key = _read_key()
            if key in ("q", "esc"):
                return
            elif key == "i" and not is_inst:
                self._install_flow(app_id)
                self._reload()
            elif key == "r" and is_inst:
                self._remove_flow(app_id)
                self._reload()
                if app_id not in self._installed:
                    return  # go back after removal
            elif key == "u" and is_inst:
                _clear()
                self._header(f"Updating {name}...")
                _show_cursor()
                self.mgr.update(app_name=app_id)
                _hide_cursor()
                self._reload()
                _pause()
            elif key == "o" and repo:
                self._open_url(repo)
            elif key == "l":
                self._show_changelog(app_id)

    def _show_changelog(self, app_id: str):
        _clear()
        self._header(f"Changelog \u2014 {app_id}")
        _w(f"\n  {_C.GRAY}Fetching from GitHub...{_C.RST}")
        _show_cursor()
        changelog = self.mgr.fetch_app_changelog(app_id, self._registry)
        _hide_cursor()
        _clear()
        self._header(f"Changelog \u2014 {app_id}")
        if changelog:
            for entry in changelog:
                # highlight version prefix
                if ":" in entry:
                    ver_part, rest = entry.split(":", 1)
                    _w(f"\n   {_C.BCYAN}{ver_part}{_C.RST}:{rest}")
                else:
                    _w(f"\n   {entry}")
        else:
            _w(f"\n  {_C.GRAY}No changelog available.{_C.RST}")
        _w("\n")
        _pause()

    # -- Install flow ---------------------------------------------------------

    def _install_flow(self, app_id: str = None):
        if app_id is None:
            return

        info = self._apps.get(app_id, {})
        name = info.get("name", app_id)
        compat = self.mgr._is_compatible(info)

        _clear()
        self._header(f"Install {name}")
        _w(f"\n  {info.get('description', '')}\n")

        if not compat:
            plats = ", ".join(info.get("platforms", []))
            _w(f"\n  {_C.BYELLOW}\u26a0 Not designed for "
               f"{self.config.platform}{_C.RST}\n")
            _w(f"  {_C.GRAY}Supported: {plats}{_C.RST}\n")

        _w("\n")
        ref = _text_input("Branch/tag/commit", "main")
        if ref is None:
            return

        _w("\n")
        req_str = self.mgr._format_requires(info)
        if req_str:
            _w(f"  {_C.GRAY}Dependencies: {req_str}{_C.RST}\n")

        if not _confirm(f"Install {name} ({ref})?"):
            return

        _clear()
        self._header(f"Installing {name}...")
        _show_cursor()
        self.mgr.install(app_id, ref=ref, force=True)
        _hide_cursor()
        _pause()

    # -- Remove flow ----------------------------------------------------------

    def _remove_flow(self, app_id: str):
        info = self._apps.get(app_id, {})
        name = info.get("name", app_id)

        if not _confirm(f"Remove {name}? This cannot be undone"):
            return

        _clear()
        self._header(f"Removing {name}...")
        _show_cursor()
        self.mgr.remove(app_id)
        _hide_cursor()
        _pause()

    # -- Update flow ----------------------------------------------------------

    def _update_flow(self):
        _clear()
        if not self._installed:
            _w(f"\n  {_C.GRAY}No apps installed.{_C.RST}\n")
            _pause()
            return

        self._header("Update Apps")
        _w(f"\n  Updating {len(self._installed)} app(s)...\n\n")
        _show_cursor()
        self.mgr.update(update_all=True)
        _hide_cursor()
        _pause()

    # -- Quick OTA -------------------------------------------------------------

    def _quick_ota(self):
        """OTA flash with build state awareness."""
        if self.config.platform == "esp-idf":
            ota_cmd = "python3 tools/ota_flash.py"
            build_cmd = "idf.py build"
        elif self.config.platform == "arduino":
            ota_cmd = "python3 scripts/ota_flash.py"
            build_cmd = "pio run"
        else:
            _clear()
            _w(f"  {_C.GRAY}OTA not available for "
               f"this platform.{_C.RST}\n")
            _pause()
            return

        while True:
            _clear()
            self._header("OTA Flash")

            build = self.mgr.get_build_info()

            if not build["exists"]:
                _w(f"\n   {_C.BRED}\u2717 No firmware binary "
                   f"found{_C.RST}\n")
                _w(f"   {_C.GRAY}Build the project first."
                   f"{_C.RST}\n")
                self._footer("[b] Build now   q back")
                key = _read_key()
                if key == "b":
                    _clear()
                    self._header("Building...")
                    _show_cursor()
                    self.mgr.run_command(build_cmd)
                    _hide_cursor()
                    _pause()
                    continue
                return

            # Binary info
            size_str = self._fmt_size(build["size"])
            age_str = self._fmt_age(build["age_seconds"])
            path_short = os.path.basename(build["path"])

            _w(f"\n   {_C.GRAY}Binary{_C.RST}      "
               f"{_C.BWHITE}{path_short}{_C.RST}  "
               f"{_C.GRAY}({size_str}){_C.RST}\n")
            _w(f"   {_C.GRAY}Built{_C.RST}       "
               f"{age_str}\n")

            if build["stale"]:
                _w(f"\n   {_C.BYELLOW}\u26a0 Sources modified "
                   f"since last build{_C.RST}\n")
                self._footer(
                    "[enter] Flash anyway   [b] Build first   "
                    "[r] Build + Flash   q back")
            else:
                _w(f"\n   {_C.BGREEN}\u2713 Build is up to "
                   f"date{_C.RST}\n")
                self._footer("[enter] Flash   [b] Rebuild   q back")

            key = _read_key()
            if key in ("q", "esc"):
                return
            elif key == "enter":
                _clear()
                self._header("Flashing via OTA...")
                _show_cursor()
                self.mgr.run_command(ota_cmd)
                _hide_cursor()
                _pause()
                return
            elif key == "b":
                _clear()
                self._header("Building...")
                _show_cursor()
                self.mgr.run_command(build_cmd)
                _hide_cursor()
                _pause()
                continue
            elif key == "r" and build.get("stale"):
                _clear()
                self._header("Building + Flashing...")
                _show_cursor()
                rc = self.mgr.run_command(build_cmd)
                if rc == 0:
                    _w(f"\n  {_C.BGREEN}\u2713 Build OK"
                       f"{_C.RST}, starting OTA...\n\n")
                    self.mgr.run_command(ota_cmd)
                _hide_cursor()
                _pause()
                return

    # -- Build & Flash --------------------------------------------------------

    def _build_flash(self):
        plat = self.config.platform

        if plat == "esp-idf":
            commands = [
                ("Full Clean + Build",
                 "idf.py fullclean && idf.py build"),
                ("Build",
                 "idf.py build"),
                ("Flash (UART)",
                 "idf.py{port} flash"),
                ("Flash (OTA)",
                 "python3 tools/ota_flash.py"),
                ("Monitor",
                 "idf.py{port} monitor"),
                ("Flash + Monitor",
                 "idf.py{port} flash monitor"),
            ]
        elif plat == "arduino":
            commands = [
                ("Clean + Build",
                 "pio run --target clean && pio run"),
                ("Build",
                 "pio run"),
                ("Upload",
                 "pio run --target upload"),
                ("Monitor",
                 "pio device monitor"),
                ("Upload + Monitor",
                 "pio run --target upload && pio device monitor"),
            ]
        else:
            commands = [
                ("Build",
                 "cmake --build build"),
                ("Clean + Build",
                 "rm -rf build && cmake -B build && cmake --build build"),
                ("Run",
                 "./build/crosspad"),
            ]

        cursor = 0
        while True:
            _clear()

            if (not self._serial_port
                    and plat in ("esp-idf", "arduino")):
                self._serial_port = self.mgr.detect_serial_port()

            port_flag = (f" -p {self._serial_port}"
                         if self._serial_port else "")

            self._header("Build & Flash", plat)

            # port info
            if plat in ("esp-idf", "arduino"):
                if self._serial_port:
                    _w(f"   {_C.GRAY}Port:{_C.RST} "
                       f"{_C.BWHITE}{self._serial_port}{_C.RST}"
                       f"      {_C.GRAY}[p] change{_C.RST}\n")
                else:
                    _w(f"   {_C.BYELLOW}Port: not detected{_C.RST}"
                       f"      {_C.GRAY}[p] set manually{_C.RST}\n")
            _w("\n")

            for i, (label, cmd) in enumerate(commands):
                display_cmd = cmd.replace("{port}", port_flag)
                if i == cursor:
                    _w(f"  {_C.BYELLOW}> {label:<24}{_C.RST} "
                       f"{_C.GRAY}{display_cmd}{_C.RST}\n")
                else:
                    _w(f"    {label:<24} "
                       f"{_C.DIM}{display_cmd}{_C.RST}\n")

            self._footer(
                "\u2191\u2193 navigate   enter run   "
                + ("[p] set port   " if plat in ("esp-idf", "arduino") else "")
                + "q back"
            )

            key = _read_key()
            if key == "up":
                cursor = (cursor - 1) % len(commands)
            elif key == "down":
                cursor = (cursor + 1) % len(commands)
            elif key == "enter":
                cmd = commands[cursor][1].replace("{port}", port_flag)
                _clear()
                _show_cursor()
                self.mgr.run_command(cmd)
                _hide_cursor()
                _pause()
            elif key == "p" and plat in ("esp-idf", "arduino"):
                port = _text_input("Serial port", self._serial_port)
                if port is not None:
                    self._serial_port = port
            elif key in ("q", "esc"):
                break

    # -- Health ---------------------------------------------------------------

    def _health(self):
        while True:
            _clear()
            self._header("Project Health")

            # -- submodules --
            self._section("Components")
            subs = self.mgr.get_all_submodules()
            if subs:
                for s in subs:
                    dirty = self.mgr.get_submodule_dirty(s["path"])
                    if s["modified"]:
                        st = f"{_C.BYELLOW}\u2195 modified{_C.RST}"
                    elif s["uninitialized"]:
                        st = f"{_C.BRED}\u2717 uninit{_C.RST}  "
                    elif dirty:
                        st = f"{_C.BYELLOW}\u26a0 dirty{_C.RST}   "
                    else:
                        st = f"{_C.BGREEN}\u2713 clean{_C.RST}   "

                    tag = (f"{_C.DIM}(infra){_C.RST}" if s["infra"]
                           else f"{_C.CYAN}(app){_C.RST}" if s["is_app"]
                           else "")

                    _w(f"   {st}  {s['name']:<30} "
                       f"{_C.GRAY}{s['commit']}{_C.RST}  {tag}\n")
            else:
                _w(f"   {_C.GRAY}No submodules found.{_C.RST}\n")

            # -- manifest sync check --
            self._section("Status")

            orphans = []
            missing = []
            for aid in self._installed:
                info = self._apps.get(aid, {})
                if info:
                    path = self.mgr._resolve_install_path(info)
                    if not (self.mgr.project_dir / path).exists():
                        missing.append(aid)

            for aid, info in self._apps.items():
                path = self.mgr._resolve_install_path(info)
                full = self.mgr.project_dir / path
                if (full.exists() and (full / ".git").exists()
                        and aid not in self._installed):
                    orphans.append(aid)

            if not orphans and not missing:
                _w(f"   {_C.BGREEN}\u2713{_C.RST} Manifest"
                   f"      synced with disk\n")
            else:
                if orphans:
                    _w(f"   {_C.BYELLOW}\u26a0{_C.RST} Manifest"
                       f"      {len(orphans)} orphan(s): "
                       f"{', '.join(orphans)}\n")
                if missing:
                    _w(f"   {_C.BRED}\u2717{_C.RST} Manifest"
                       f"      {len(missing)} missing: "
                       f"{', '.join(missing)}\n")

            # cache age
            cache_age = self.mgr.get_cache_age()
            if cache_age < 0:
                _w(f"   {_C.BYELLOW}\u26a0{_C.RST} Registry"
                   f"      not cached\n")
            elif cache_age < CACHE_MAX_AGE_SECONDS:
                _w(f"   {_C.BGREEN}\u2713{_C.RST} Registry"
                   f"      cached {self._fmt_age(cache_age)}\n")
            else:
                _w(f"   {_C.BYELLOW}\u26a0{_C.RST} Registry"
                   f"      stale ({self._fmt_age(cache_age)})\n")

            # gh auth
            auth_ok, auth_user = self.mgr.check_gh_auth()
            if auth_ok:
                _w(f"   {_C.BGREEN}\u2713{_C.RST} gh CLI"
                   f"        authenticated ({auth_user})\n")
            else:
                _w(f"   {_C.BRED}\u2717{_C.RST} gh CLI"
                   f"        not authenticated\n")

            self._footer("[s] Sync manifest   [r] Refresh registry   q back")

            key = _read_key()
            if key in ("q", "esc"):
                break
            elif key == "s":
                _clear()
                self._header("Syncing manifest...")
                _show_cursor()
                self.mgr.sync()
                _hide_cursor()
                self._reload()
                _pause()
            elif key == "r":
                _clear()
                self._header("Refreshing registry...")
                _show_cursor()
                self.mgr._fetch_remote_registry()
                _hide_cursor()
                self._reload()
                _w(f"\n  {_C.BGREEN}\u2713{_C.RST} "
                   f"Registry refreshed.\n")
                _pause()

    # -- Dev Tools ------------------------------------------------------------

    def _dev_tools(self):
        tools = [
            ("Force refresh registry",
             "Bypass cache, fetch fresh from GitHub"),
            ("View registry data",
             f"Show all {len(self._apps)} apps in registry"),
            ("View manifest data",
             "Show installed apps manifest (apps.json)"),
            ("Clear cache",
             "Delete local registry cache file"),
            ("Open crosspad-apps repo",
             "Open registry repo in browser"),
            ("Sync manifest",
             "Match manifest to submodules on disk"),
        ]
        cursor = 0

        while True:
            _clear()
            self._header("Developer Tools")
            _w("\n")

            for i, (label, desc) in enumerate(tools):
                if i == cursor:
                    _w(f"  {_C.BYELLOW}> {label}{_C.RST}\n")
                    _w(f"    {_C.GRAY}{desc}{_C.RST}\n")
                else:
                    _w(f"    {label}\n")

            self._footer(
                "\u2191\u2193 navigate   enter select   q back")

            key = _read_key()
            if key == "up":
                cursor = (cursor - 1) % len(tools)
            elif key == "down":
                cursor = (cursor + 1) % len(tools)
            elif key == "enter":
                self._run_dev_tool(cursor)
            elif key in ("q", "esc"):
                break

    def _run_dev_tool(self, idx: int):
        _clear()
        _show_cursor()

        if idx == 0:  # force refresh
            self._header("Refreshing registry...")
            self.mgr._fetch_remote_registry()
            self._reload()
            _w(f"\n  {_C.BGREEN}\u2713{_C.RST} Registry refreshed.\n")

        elif idx == 1:  # view registry
            self._header("Registry Data")
            for app_id, info in self._apps.items():
                compat = self.mgr._is_compatible(info)
                icon = (_C.GREEN if compat else _C.RED)
                _w(f"\n  {icon}\u25cf{_C.RST} "
                   f"{_C.BWHITE}{app_id}{_C.RST}\n")
                for k in ("name", "version", "description", "category",
                           "platforms", "requires", "repo"):
                    v = info.get(k, "")
                    if v:
                        _w(f"    {_C.GRAY}{k}:{_C.RST} {v}\n")

        elif idx == 2:  # view manifest
            self._header("Manifest Data (apps.json)")
            if self._installed:
                for app_id, inst in self._installed.items():
                    _w(f"\n  {_C.BWHITE}{app_id}{_C.RST}\n")
                    for k, v in inst.items():
                        _w(f"    {_C.GRAY}{k}:{_C.RST} {v}\n")
            else:
                _w(f"\n  {_C.GRAY}No apps installed.{_C.RST}\n")

        elif idx == 3:  # clear cache
            if self.mgr.local_registry_path.exists():
                self.mgr.local_registry_path.unlink()
                _w(f"\n  {_C.BGREEN}\u2713{_C.RST} "
                   f"Cache cleared.\n")
            else:
                _w(f"\n  {_C.GRAY}No cache file found.{_C.RST}\n")

        elif idx == 4:  # open repo
            self._open_url(
                f"https://github.com/{REMOTE_REGISTRY_REPO}")
            _w(f"\n  {_C.GRAY}Opening in browser...{_C.RST}\n")

        elif idx == 5:  # sync
            self._header("Syncing manifest...")
            self.mgr.sync()
            self._reload()

        _hide_cursor()
        _pause()


# -- entry point --------------------------------------------------------------

def tui_main(config: PlatformConfig):
    """Launch the interactive TUI."""
    if not _is_interactive():
        print("Error: TUI requires an interactive terminal.")
        sys.exit(1)
    _TUI(config).run()
