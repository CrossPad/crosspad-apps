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
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


REMOTE_REGISTRY_REPO = "CrossPad/crosspad-apps"
REMOTE_REGISTRY_PATH = "registry.json"
LOCAL_REGISTRY_FILE = "app-registry.json"
MANIFEST_FILE = "apps.json"           # state: what is on disk (machine-written)
CONFIG_FILE = "crosspad.config.json"  # intent: apps, track policy, features
LOCAL_CONFIG_FILE = "crosspad.local.json"  # personal overrides (gitignored)
WORK_ROOT = ".crosspad"               # generated + backup working data
BACKUP_ROOT = ".crosspad/backups"
PROFILE_DIR = "config/profiles"
FEATURES_SCHEMA = "features.schema.json"
CACHE_MAX_AGE_SECONDS = 3600  # 1 hour

# Per-app tracking policy. The mode is intent; the blocking flags below are
# observed reality and override it — a registry-tracked app that carries
# uncommitted work is still protected.
TRACK_REGISTRY = "registry"   # follow the registry/manifest ref, ff-only
TRACK_BRANCH = "branch"       # follow the user's branch, never switch away
TRACK_PINNED = "pinned"       # never moves
TRACK_LOCAL = "local"         # manager does not touch the worktree at all
TRACK_MODES = (TRACK_REGISTRY, TRACK_BRANCH, TRACK_PINNED, TRACK_LOCAL)

BLOCKING_FLAGS = ("dirty", "ahead", "branch-mismatch", "fork")


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
        self.config_path = self.project_dir / CONFIG_FILE
        self.local_config_path = self.project_dir / LOCAL_CONFIG_FILE

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

    def _get_submodule_branch(self, path: str) -> str | None:
        """Branch a submodule is actually checked out on, or None if detached.

        `git submodule status` appends the described ref, e.g.
        "(heads/master)". That is the branch a later `update` must follow —
        the manifest's recorded ref is only what was asked for at install time
        and drifts as soon as anyone checks out something else.
        """
        result = self._git("submodule", "status", path, check=False, capture=True)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        line = result.stdout.strip()
        if "(" not in line or not line.endswith(")"):
            return None
        described = line[line.rindex("(") + 1:-1]
        if described.startswith("heads/"):
            return described[len("heads/"):]
        return None

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
                                 "crosspad-platform-idf",
                                 "FreeRTOS", "lvgl")
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
        elif self.config.platform == "pc":
            candidates = [
                self.project_dir / "bin" / "CrossPad",
                self.project_dir / "bin" / "CrossPad.exe",
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
        src_dirs = ["main", "components", "src"]
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

    # -- project config: intent vs state --------------------------------------
    #
    # apps.json records what is ON DISK (state, machine-written). The project
    # config records what the user WANTS (intent, hand- or TUI-edited): which
    # apps, how each one is tracked, which board and feature flags. Keeping the
    # two apart is what makes it safe to say "this submodule is mine, hands off"
    # without the manager overwriting the statement on the next sync.

    def _load_config_raw(self) -> dict:
        if self.config_path.exists():
            with open(self.config_path) as f:
                return json.load(f)
        return {}

    def _load_local_config(self) -> dict:
        if self.local_config_path.exists():
            with open(self.local_config_path) as f:
                return json.load(f)
        return {}

    def load_config(self) -> dict:
        """Merged intent: crosspad.config.json overlaid with crosspad.local.json.

        The local file is gitignored, so a developer can park an app on their
        own branch without that showing up as a repo change for everyone else.
        """
        cfg = self._load_config_raw()
        local = self._load_local_config()
        for key, value in local.items():
            if key in ("apps", "features") and isinstance(value, dict):
                merged = dict(cfg.get(key, {}))
                merged.update(value)
                cfg[key] = merged
            else:
                cfg[key] = value
        return cfg

    def save_config(self, cfg: dict, local: bool = False):
        path = self.local_config_path if local else self.config_path
        with open(path, "w") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")

    def app_policy(self, app_id: str) -> dict:
        """Track policy for one app. Defaults to registry-tracked."""
        entry = self.load_config().get("apps", {}).get(app_id)
        if not isinstance(entry, dict):
            return {"track": TRACK_REGISTRY}
        track = entry.get("track", TRACK_REGISTRY)
        if track not in TRACK_MODES:
            track = TRACK_REGISTRY
        out = {"track": track}
        if entry.get("ref"):
            out["ref"] = entry["ref"]
        if entry.get("commit"):
            out["commit"] = entry["commit"]
        return out

    def set_app_policy(self, app_id: str, track: str, ref: str = None,
                       commit: str = None, local: bool = False):
        if track not in TRACK_MODES:
            raise ValueError(f"unknown track mode '{track}'")
        target = self._load_local_config() if local else self._load_config_raw()
        target.setdefault("version", 1)
        entry = {"track": track}
        if ref:
            entry["ref"] = ref
        if commit:
            entry["commit"] = commit
        target.setdefault("apps", {})[app_id] = entry
        self.save_config(target, local=local)

    def ensure_config(self, quiet: bool = False) -> dict:
        """Create crosspad.config.json from the current state if absent.

        Migration is deliberately conservative: everything becomes
        registry-tracked except submodules already sitting on a non-default
        branch, which become branch-tracked on the branch they are on. That
        preserves e.g. a mixer parked on crosspad_v20 instead of quietly
        dragging it back to main on the next update.
        """
        if self.config_path.exists():
            return self._load_config_raw()

        manifest = self._load_manifest()
        registry = self._load_registry()
        apps_reg = registry.get("apps", {})
        cfg = {"version": 1, "platform": self.config.platform,
               "features": {}, "apps": {}}

        for app_id in manifest.get("installed", {}):
            info = apps_reg.get(app_id, {})
            path = (self._resolve_install_path(info) if info else
                    f"{self.config.lib_dir}/{self.config.lib_prefix}{app_id}")
            branch = self._get_submodule_branch(path)
            default = self._get_default_branch(path) if branch else None
            if branch and branch != default:
                cfg["apps"][app_id] = {"track": TRACK_BRANCH, "ref": branch}
            else:
                cfg["apps"][app_id] = {"track": TRACK_REGISTRY}

        self.save_config(cfg)
        if not quiet:
            print(f"Created {CONFIG_FILE} from current state "
                  f"({len(cfg['apps'])} app(s)).")
        return cfg

    # -- observed git state ---------------------------------------------------

    def _sub_git(self, path: str, *args, timeout: int = 20):
        return subprocess.run(
            ["git", "-C", str(self.project_dir / path)] + list(args),
            capture_output=True, text=True, check=False, timeout=timeout)

    def app_git_state(self, path: str) -> dict:
        """Raw git facts about a submodule worktree. No policy applied."""
        full = self.project_dir / path
        state = {"exists": full.exists(), "branch": None, "head": None,
                 "upstream": None, "ahead": 0, "behind": 0, "dirty": 0,
                 "untracked": 0, "stashes": 0, "detached": False,
                 "origin": "", "fork": False}
        if not full.exists() or not (full / ".git").exists():
            return state

        r = self._sub_git(path, "rev-parse", "--abbrev-ref", "HEAD")
        branch = r.stdout.strip() if r.returncode == 0 else ""
        if branch == "HEAD" or not branch:
            state["detached"] = True
        else:
            state["branch"] = branch

        r = self._sub_git(path, "rev-parse", "--short", "HEAD")
        if r.returncode == 0:
            state["head"] = r.stdout.strip()

        r = self._sub_git(path, "rev-parse", "--abbrev-ref",
                          "--symbolic-full-name", "@{u}")
        if r.returncode == 0 and r.stdout.strip():
            state["upstream"] = r.stdout.strip()
            c = self._sub_git(path, "rev-list", "--left-right", "--count",
                              "@{u}...HEAD")
            if c.returncode == 0 and c.stdout.split():
                parts = c.stdout.split()
                state["behind"] = int(parts[0])
                state["ahead"] = int(parts[1]) if len(parts) > 1 else 0

        # Commits that exist nowhere on origin count as local work even when
        # there is no upstream to compare against (detached submodule with
        # hand-made commits on top is the common case).
        if not state["upstream"]:
            c = self._sub_git(path, "rev-list", "--count", "HEAD",
                              "--not", "--remotes=origin")
            if c.returncode == 0 and c.stdout.strip().isdigit():
                state["ahead"] = int(c.stdout.strip())

        r = self._sub_git(path, "status", "--porcelain")
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if line.startswith("??"):
                    state["untracked"] += 1
                elif line.strip():
                    state["dirty"] += 1

        r = self._sub_git(path, "stash", "list")
        if r.returncode == 0:
            state["stashes"] = len([l for l in r.stdout.splitlines() if l.strip()])

        r = self._sub_git(path, "remote", "get-url", "origin")
        if r.returncode == 0:
            state["origin"] = r.stdout.strip()
            state["fork"] = bool(state["origin"]) and \
                f"/{self.config.official_org}/".lower() not in \
                state["origin"].lower().replace(":", "/")
        return state

    def app_status(self, app_id: str) -> dict:
        """Policy + observed state + a verdict for mutating operations."""
        registry = self._load_registry()
        info = registry.get("apps", {}).get(app_id, {})
        path = (self._resolve_install_path(info) if info else
                f"{self.config.lib_dir}/{self.config.lib_prefix}{app_id}")
        policy = self.app_policy(app_id)
        git = self.app_git_state(path)

        flags = []
        if git["dirty"]:
            flags.append("dirty")
        if git["ahead"]:
            flags.append("ahead")
        if git["stashes"]:
            flags.append("stashed")
        if git["fork"]:
            flags.append("fork")

        # Which ref this app is supposed to follow. For registry tracking that
        # is the manifest ref (what install/sync recorded); for branch tracking
        # it is the branch named in the config.
        manifest = self._load_manifest()
        inst = manifest.get("installed", {}).get(app_id, {})
        want_ref = policy.get("ref") or inst.get("ref") or "main"
        if git["branch"] and git["branch"] != want_ref:
            flags.append("branch-mismatch")

        blocking = [f for f in flags if f in BLOCKING_FLAGS]
        return {
            "app": app_id, "path": path, "policy": policy, "git": git,
            "want_ref": want_ref, "flags": flags, "blocking": blocking,
            "protected": policy["track"] in (TRACK_LOCAL, TRACK_PINNED),
        }

    @staticmethod
    def describe_status(st: dict) -> str:
        git = st["git"]
        if not git["exists"]:
            return "missing"
        bits = []
        bits.append(git["branch"] or f"detached@{git['head']}")
        if git["ahead"]:
            bits.append(f"↑{git['ahead']}")
        if git["behind"]:
            bits.append(f"↓{git['behind']}")
        if git["dirty"]:
            bits.append(f"✎{git['dirty']}")
        if git["untracked"]:
            bits.append(f"+{git['untracked']}?")
        if git["stashes"]:
            bits.append(f"stash:{git['stashes']}")
        if git["fork"]:
            bits.append("fork")
        return " ".join(bits)

    # -- backup / restore -----------------------------------------------------

    def backup_dir(self, app_id: str) -> Path:
        return self.project_dir / BACKUP_ROOT / app_id

    def list_backups(self, app_id: str) -> list[str]:
        root = self.backup_dir(app_id)
        if not root.exists():
            return []
        return sorted((d.name for d in root.iterdir() if d.is_dir()),
                      reverse=True)

    def backup_app(self, app_id: str, prune_keep: int = 10) -> str | None:
        """Snapshot every scrap of local work in an app submodule.

        Captures, in this order: tracked modifications as a patch, untracked
        files as a tarball, commits that exist nowhere on origin as a git
        bundle, and every stash as its own patch. Enough to reconstruct the
        worktree after a destructive checkout.
        """
        st = self.app_status(app_id)
        path, git = st["path"], st["git"]
        if not git["exists"]:
            return None

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = self.backup_dir(app_id) / ts
        dest.mkdir(parents=True, exist_ok=True)

        if git["dirty"]:
            r = self._sub_git(path, "diff", "HEAD")
            (dest / "tracked.patch").write_text(r.stdout)

        if git["untracked"]:
            full = self.project_dir / path
            files = self._sub_git(path, "ls-files", "--others",
                                  "--exclude-standard")
            names = [f for f in files.stdout.splitlines() if f.strip()]
            if names:
                import tarfile
                with tarfile.open(dest / "untracked.tgz", "w:gz") as tar:
                    for name in names:
                        src = full / name
                        if src.exists():
                            tar.add(src, arcname=name)

        if git["ahead"]:
            bundle = dest / "local-commits.bundle"
            # Bundle the branch by name when there is one; a bundle whose only
            # ref is "HEAD" restores into nothing useful, because the fetch
            # refspec has no branch name to map.
            refs = ["HEAD"] if git["detached"] else [f"refs/heads/{git['branch']}"]
            r = self._sub_git(path, "bundle", "create", str(bundle),
                              *refs, "--not", "--remotes=origin")
            if r.returncode != 0 and bundle.exists():
                bundle.unlink()

        if git["stashes"]:
            sdir = dest / "stashes"
            sdir.mkdir(exist_ok=True)
            listing = self._sub_git(path, "stash", "list")
            for i, line in enumerate(listing.stdout.splitlines()):
                if not line.strip():
                    continue
                p = self._sub_git(path, "stash", "show", "-p", f"stash@{{{i}}}")
                (sdir / f"stash{i}.patch").write_text(p.stdout)
            (sdir / "list.txt").write_text(listing.stdout)

        meta = {
            "app": app_id, "path": path, "timestamp": ts,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "branch": git["branch"], "head": git["head"],
            "upstream": git["upstream"], "origin": git["origin"],
            "flags": st["flags"], "policy": st["policy"],
        }
        (dest / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

        # Keep the backup tree bounded; it is gitignored working data, not history.
        backups = self.list_backups(app_id)
        if len(backups) > prune_keep:
            import shutil
            for old in backups[prune_keep:]:
                shutil.rmtree(self.backup_dir(app_id) / old, ignore_errors=True)

        return str(dest)

    def restore_backup(self, app_id: str, stamp: str = None) -> bool:
        """Replay a backup onto the current worktree.

        Patches and untracked files land back in place; local commits are
        fetched into refs/crosspad-backup/<ts>/* rather than being replayed
        onto whatever is checked out now — reconstructing history is the
        user's call, not ours.
        """
        backups = self.list_backups(app_id)
        if not backups:
            print(f"No backups for '{app_id}'.")
            return False
        stamp = stamp or backups[0]
        src = self.backup_dir(app_id) / stamp
        if not src.exists():
            print(f"No backup '{stamp}' for '{app_id}'.")
            return False

        st = self.app_status(app_id)
        path = st["path"]
        if not st["git"]["exists"]:
            print(f"'{app_id}' is not on disk; install it first.")
            return False

        print(f"Restoring {app_id} from {stamp}...")
        ok = True

        untracked = src / "untracked.tgz"
        if untracked.exists():
            import tarfile
            with tarfile.open(untracked) as tar:
                tar.extractall(self.project_dir / path)
            print("  untracked files restored")

        patch = src / "tracked.patch"
        if patch.exists() and patch.stat().st_size:
            r = self._sub_git(path, "apply", "--3way", str(patch))
            if r.returncode != 0:
                r = self._sub_git(path, "apply", str(patch))
            if r.returncode == 0:
                print("  tracked changes applied")
            else:
                ok = False
                print(f"  patch did NOT apply: {r.stderr.strip().splitlines()[:1]}")
                print(f"  patch kept at {patch}")

        bundle = src / "local-commits.bundle"
        if bundle.exists():
            # Enumerate what the bundle actually carries instead of assuming a
            # refspec: a detached-HEAD backup stores "HEAD", a branch backup
            # stores refs/heads/<name>, and a wildcard fetch silently matches
            # neither of those in the wrong case.
            heads = self._sub_git(path, "bundle", "list-heads", str(bundle))
            specs, names = [], []
            for line in heads.stdout.splitlines():
                parts = line.split()
                if len(parts) < 2:
                    continue
                name = parts[1].rsplit("/", 1)[-1]
                dst = f"refs/crosspad-backup/{stamp}/{name}"
                specs.append(f"{parts[1]}:{dst}")
                names.append(dst)
            if specs:
                r = self._sub_git(path, "fetch", str(bundle), *specs)
                if r.returncode == 0:
                    print(f"  local commits fetched into "
                          f"{', '.join(names)}")
                    print(f"    inspect: git -C {path} log "
                          f"{names[0]}")
                else:
                    ok = False
                    print(f"  bundle fetch failed: {r.stderr.strip()}")
            else:
                ok = False
                print(f"  bundle carries no refs: {bundle}")

        stashes = src / "stashes"
        if stashes.exists():
            print(f"  stash patches left at {stashes} (apply manually)")
        return ok

    def park_wip(self, app_id: str) -> bool:
        """Commit the worktree onto a wip/ branch so the app reads as clean."""
        st = self.app_status(app_id)
        path, git = st["path"], st["git"]
        if not (git["dirty"] or git["untracked"]):
            return True
        branch = f"wip/{datetime.now().strftime('%Y%m%d-%H%M%S')}-{app_id}"
        r = self._sub_git(path, "checkout", "-b", branch)
        if r.returncode != 0:
            print(f"  could not create {branch}: {r.stderr.strip()}")
            return False
        self._sub_git(path, "add", "-A")
        r = self._sub_git(path, "commit", "-m",
                          f"wip({app_id}): parked by crosspad app manager")
        if r.returncode != 0:
            print(f"  commit failed: {r.stderr.strip()}")
            return False
        print(f"  parked on {branch}")
        return True

    # -- guard ----------------------------------------------------------------

    def guard(self, app_id: str, force: bool = False,
              backup: bool = True) -> tuple[bool, str]:
        """Preflight before a destructive operation.

        Returns (may_proceed, reason). A protected app never proceeds; an app
        carrying local work proceeds only under --force, and even then a backup
        is taken first.
        """
        st = self.app_status(app_id)
        if st["protected"]:
            return False, f"track={st['policy']['track']}"
        if not st["blocking"]:
            return True, ""
        reason = ", ".join(st["blocking"])
        if not force:
            return False, reason
        if backup:
            dest = self.backup_app(app_id)
            if dest:
                print(f"  backup: {dest}")
        return True, f"forced over {reason}"

    # -- feature flags (Marlin-style compile-time config) ----------------------
    #
    # crosspad-core owns the catalog (features.schema.json next to
    # Configuration.h). The project config owns the chosen values. Nothing here
    # ever writes into the submodule: overrides leave as -D definitions in
    # .crosspad/build_flags.*, so a project with no overrides builds exactly
    # like the checked-in headers say it should.

    def schema_path(self) -> Path | None:
        for base in (self.config.lib_dir, "lib", "components", "."):
            p = (self.project_dir / base / "crosspad-core" / "include" /
                 "crosspad" / "config" / FEATURES_SCHEMA)
            if p.exists():
                return p
        return None

    def load_feature_schema(self) -> dict:
        p = self.schema_path()
        if not p:
            return {"flags": [], "groups": []}
        try:
            with open(p) as f:
                return json.load(f)
        except (OSError, ValueError) as e:
            print(f"Warning: cannot read {FEATURES_SCHEMA}: {e}")
            return {"flags": [], "groups": []}

    def _flag_managed_elsewhere(self, flag: dict) -> str | None:
        """Some flags are owned by another build system on some platforms.

        CROSSPAD_BOARD on ESP-IDF is the case that matters: Kconfig picks the
        board revision and CMake bridges it to CROSSPAD_BOARD, so emitting a
        second -D here would fight the BSP pinout selection.
        """
        managed = flag.get("managed_by", {})
        return managed.get(self.config.platform)

    def _managed_value(self, flag: dict) -> str | None:
        """Read a flag whose value another build system owns.

        CROSSPAD_BOARD on ESP-IDF is picked by Kconfig; showing the schema
        default there would be a lie, and a config screen that lies is worse
        than one that omits the row.
        """
        source = flag.get("managed_source", {}).get(self.config.platform)
        if not source:
            return None
        path = self.project_dir / source.get("file", "")
        if not path.exists():
            return None
        try:
            text = path.read_text()
        except OSError:
            return None
        for needle, value in source.get("match", {}).items():
            if needle in text:
                return value
        return None

    def feature_values(self) -> dict:
        """Effective value per flag: schema default overlaid with config."""
        chosen = self.load_config().get("features", {})
        out = {}
        for flag in self.load_feature_schema().get("flags", []):
            name = flag["name"]
            managed = self._managed_value(flag)
            out[name] = (managed if managed is not None
                         else chosen.get(name, flag.get("default")))
        return out

    def set_feature(self, name: str, value, local: bool = False):
        target = self._load_local_config() if local else self._load_config_raw()
        target.setdefault("version", 1)
        schema = {f["name"]: f for f in self.load_feature_schema().get("flags", [])}
        features = target.setdefault("features", {})
        if name in schema and value == schema[name].get("default"):
            features.pop(name, None)   # back to default: stop overriding
        else:
            features[name] = value
        self.save_config(target, local=local)

    def validate_features(self) -> list[str]:
        """Check `requires` expressions. The compiler is still the authority."""
        values = self.feature_values()
        problems = []
        for flag in self.load_feature_schema().get("flags", []):
            name = flag["name"]
            if not values.get(name):
                continue
            for req in flag.get("requires", []):
                if "==" not in req:
                    continue
                dep, want = (x.strip() for x in req.split("==", 1))
                have = values.get(dep)
                if str(have) != want:
                    problems.append(
                        f"{name} requires {dep}=={want} (is {have})")
        return problems

    def feature_overrides(self) -> list[str]:
        """-D definitions for every flag that deviates from its default."""
        values = self.feature_values()
        defs = []
        for flag in self.load_feature_schema().get("flags", []):
            name = flag["name"]
            if self._flag_managed_elsewhere(flag):
                continue
            value = values.get(name)
            if value == flag.get("default"):
                continue
            if flag.get("type") == "bool":
                defs.append(f"{name}={1 if value else 0}")
            else:
                defs.append(f"{name}={value}")
        return defs

    def flags_hash(self) -> str:
        import hashlib
        defs = sorted(self.feature_overrides())
        return hashlib.sha256("\n".join(defs).encode()).hexdigest()[:12]

    def generate_build_flags(self) -> dict:
        """Emit the -D overrides for the platform's build system."""
        defs = self.feature_overrides()
        work = self.project_dir / WORK_ROOT
        work.mkdir(parents=True, exist_ok=True)
        digest = self.flags_hash()
        header = ("# Generated by the CrossPad app manager from "
                  f"{CONFIG_FILE}. Do not edit.\n"
                  f"# Flag set: {digest}\n")

        cmake_path = work / "build_flags.cmake"
        body = header + f'set(CROSSPAD_FLAGS_HASH "{digest}")\n'
        if defs:
            body += "add_compile_definitions(\n"
            body += "".join(f"    {d}\n" for d in defs)
            body += ")\n"
        cmake_path.write_text(body)

        ini_path = work / "build_flags.ini"
        ini = header.replace("#", ";") + "[crosspad_flags]\nbuild_flags ="
        ini += "".join(f" -D{d}" for d in defs) + "\n"
        ini_path.write_text(ini)

        (work / "flags.hash").write_text(digest + "\n")
        return {"defs": defs, "hash": digest,
                "cmake": str(cmake_path), "ini": str(ini_path)}

    def build_flags_stale(self) -> bool:
        """True when the last build used a different flag set."""
        marker = self.project_dir / WORK_ROOT / "built.hash"
        if not marker.exists():
            return bool(self.feature_overrides())
        return marker.read_text().strip() != self.flags_hash()

    def mark_build_flags_built(self):
        work = self.project_dir / WORK_ROOT
        work.mkdir(parents=True, exist_ok=True)
        (work / "built.hash").write_text(self.flags_hash() + "\n")

    # -- profiles -------------------------------------------------------------

    def profile_dir(self) -> Path:
        return self.project_dir / PROFILE_DIR

    def list_profiles(self) -> list[str]:
        d = self.profile_dir()
        if not d.exists():
            return []
        return sorted(p.stem for p in d.glob("*.json"))

    def load_profile(self, name: str) -> dict | None:
        p = self.profile_dir() / f"{name}.json"
        if not p.exists():
            return None
        try:
            with open(p) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def save_profile(self, name: str, description: str = "") -> str:
        cfg = self.load_config()
        prof = {
            "name": name,
            "description": description,
            "platform": self.config.platform,
            "features": dict(cfg.get("features", {})),
            "apps": dict(cfg.get("apps", {})),
        }
        d = self.profile_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{name}.json"
        with open(path, "w") as f:
            json.dump(prof, f, indent=2)
            f.write("\n")
        return str(path)

    def profile_plan(self, name: str) -> dict | None:
        """Diff the current project against a profile. Changes nothing."""
        prof = self.load_profile(name)
        if prof is None:
            return None
        cfg = self.load_config()
        values = self.feature_values()
        manifest = self._load_manifest().get("installed", {})

        feature_changes = []
        for flag, want in prof.get("features", {}).items():
            if values.get(flag) != want:
                feature_changes.append((flag, values.get(flag), want))

        want_apps = prof.get("apps", {})
        install, remove, retrack, protected = [], [], [], []
        for app_id, entry in want_apps.items():
            if app_id not in manifest:
                install.append((app_id, entry.get("ref", "main")))
            else:
                cur = self.app_policy(app_id)
                if cur.get("track") != entry.get("track", TRACK_REGISTRY):
                    retrack.append((app_id, cur.get("track"),
                                    entry.get("track", TRACK_REGISTRY)))
        for app_id in manifest:
            if app_id in want_apps:
                continue
            st = self.app_status(app_id)
            # A profile that does not mention an app is not a licence to delete
            # someone's work-in-progress fork of it.
            if st["protected"] or st["blocking"]:
                protected.append((app_id, ", ".join(st["blocking"]) or
                                  f"track={st['policy']['track']}"))
            else:
                remove.append(app_id)
        return {"profile": prof, "features": feature_changes,
                "install": install, "remove": remove,
                "retrack": retrack, "protected": protected}

    def apply_profile(self, name: str, remove_extra: bool = False) -> bool:
        plan = self.profile_plan(name)
        if plan is None:
            print(f"No profile '{name}'. Available: "
                  f"{', '.join(self.list_profiles()) or 'none'}")
            return False

        for flag, _old, new in plan["features"]:
            self.set_feature(flag, new)
        for app_id, ref in plan["install"]:
            self.install(app_id, ref=ref)
        for app_id, _old, new in plan["retrack"]:
            entry = plan["profile"]["apps"][app_id]
            self.set_app_policy(app_id, new, ref=entry.get("ref"),
                                commit=entry.get("commit"))
        if remove_extra:
            for app_id in plan["remove"]:
                self.remove(app_id)
        elif plan["remove"]:
            print(f"  not in profile (kept): {', '.join(plan['remove'])}")
        for app_id, reason in plan["protected"]:
            print(f"  kept (protected): {app_id} — {reason}")

        gen = self.generate_build_flags()
        print(f"  build flags: {len(gen['defs'])} override(s), "
              f"set {gen['hash']}")
        problems = self.validate_features()
        for p in problems:
            print(f"  warning: {p}")
        self._print_next_steps()
        return True

    # -- device telemetry -----------------------------------------------------
    #
    # A flashed CrossPad reports the submodules that went into its binary
    # (APP_VERSIONS over CDC). Comparing that against the project's own pins
    # answers the question the manifest cannot: is the thing on the desk
    # actually running what this checkout describes?

    CROSSPAD_USB_VID = 0x303A

    def device_port(self) -> str | None:
        """CDC port of a CrossPad running in default (CDC+MIDI) USB mode."""
        try:
            from serial.tools import list_ports
        except ImportError:
            return None
        for p in list_ports.comports():
            if p.vid == self.CROSSPAD_USB_VID:
                return p.device
        return None

    def query_device_versions(self, timeout: float = 3.0) -> dict:
        """Ask a connected device what it was built from.

        Returns {"ok": bool, "error": str, "entries": [ {...} ]}. Never raises:
        a missing pyserial, a device in USB-audio mode (no CDC) and an older
        firmware without the command are all normal states to report, not
        failures to crash on.
        """
        out = {"ok": False, "error": "", "entries": [], "port": None}
        try:
            import serial
        except ImportError:
            out["error"] = "pyserial not installed (pip install pyserial)"
            return out

        port = self.device_port()
        if not port:
            out["error"] = ("no CrossPad CDC port — device unplugged, or in "
                            "USB audio mode (no CDC there)")
            return out
        out["port"] = port

        try:
            with serial.Serial(port, 115200, timeout=0.5) as ser:
                ser.reset_input_buffer()
                ser.write(b"APP_VERSIONS\r\n")
                deadline = time.time() + timeout
                buf = ""
                while time.time() < deadline:
                    chunk = ser.read(512).decode("utf-8", "replace")
                    if chunk:
                        buf += chunk
                        if "APPVER: end" in buf:
                            break
        except Exception as e:                      # noqa: BLE001 - report it
            out["error"] = f"{type(e).__name__}: {e}"
            return out

        for line in buf.splitlines():
            line = line.strip()
            if not line.startswith("APPVER:") or line.startswith("APPVER: end"):
                continue
            body = line[len("APPVER:"):].strip()
            parts = body.split()
            entry = {"component": parts[0] if parts else "?"}
            for token in parts[1:]:
                if "=" in token:
                    k, v = token.split("=", 1)
                    entry[k] = v
            out["entries"].append(entry)

        if not out["entries"]:
            out["error"] = ("no APPVER reply — firmware predates APP_VERSIONS, "
                            "or the port is busy")
            return out
        out["ok"] = True
        return out

    def device_diff(self) -> dict:
        """Device inventory vs what this checkout has, component by component."""
        report = self.query_device_versions()
        if not report["ok"]:
            return report

        rows = []
        for entry in report["entries"]:
            component = entry.get("component", "?")
            path = f"{self.config.lib_dir}/{component}"
            local = self.app_git_state(path)
            local_commit = local["head"] or ""
            dev_commit = entry.get("commit", "")
            # The device reports a short SHA of whatever length its git printed;
            # compare on the shorter of the two so a 7-vs-8 char difference is
            # not read as a mismatch.
            n = min(len(local_commit), len(dev_commit)) or 1
            match = bool(local_commit) and local_commit[:n] == dev_commit[:n]
            rows.append({
                "component": component,
                "app_id": entry.get("id", "-"),
                "device_commit": dev_commit,
                "device_ref": entry.get("ref", "-"),
                "device_dirty": entry.get("dirty") == "1",
                "local_commit": local_commit or "?",
                "local_present": local["exists"],
                "match": match,
            })
        report["rows"] = rows
        report["stale"] = [r for r in rows if not r["match"]]
        return report

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

        info = apps[app_name]

        if info.get("built_in"):
            print(f"Error: '{app_name}' is a built-in app and cannot "
                  f"be installed or removed via the app manager.")
            return

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
            # Check lib_dir (apps), lib/ (shared deps), and project root
            candidates = [
                self.project_dir / self.config.lib_dir / req,
                self.project_dir / "lib" / req,
                self.project_dir / req,
            ]
            if not any(c.exists() for c in candidates):
                print(f"Warning: Required component '{req}' ({ver}) "
                      f"not found")

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

        # Record intent alongside state: a non-default ref means the user asked
        # for a specific branch, so track it as such instead of dragging the app
        # back to the registry ref on the next update.
        if self.config_path.exists() or self._load_manifest().get("installed"):
            self.ensure_config(quiet=True)
            default = self._get_default_branch(install_path)
            if ref and ref != default:
                self.set_app_policy(app_name, TRACK_BRANCH, ref=ref)
            else:
                self.set_app_policy(app_name, TRACK_REGISTRY)

        print(f"\n  {info['name']} installed successfully.")
        self._print_next_steps()

    def remove(self, app_name: str):
        manifest = self._load_manifest()
        registry = self._load_registry()
        apps = registry.get("apps", {})

        if apps.get(app_name, {}).get("built_in"):
            print(f"Error: '{app_name}' is a built-in app and cannot "
                  f"be removed.")
            return

        if app_name not in manifest.get("installed", {}):
            print(f"App '{app_name}' is not installed.")
            return

        info = apps.get(app_name, {})
        install_path = (self._resolve_install_path(info) if info else
                        f"{self.config.lib_dir}/{self.config.lib_prefix}"
                        f"{app_name}")

        print(f"Removing {info.get('name', app_name)}...")

        # Removal deinits the submodule, which throws away anything not pushed.
        # Always snapshot first when there is local work — no prompt, no flag:
        # a backup costs a few kB, losing a branch costs an afternoon.
        st = self.app_status(app_name)
        if st["blocking"] or st["git"]["untracked"] or st["git"]["stashes"]:
            dest = self.backup_app(app_name)
            if dest:
                print(f"  local work found ({', '.join(st['flags']) or 'untracked'})")
                print(f"  backup: {dest}")

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

    def update(self, app_name: str = None, update_all: bool = False,
               force: bool = False, dry_run: bool = False):
        """Update app submodules, honouring track policy and local work.

        Never stops on a blocked app: clean ones are updated, the rest are
        reported in a skip table with the reason. --force takes a backup and
        proceeds anyway.
        """
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

        skipped = []
        updated = 0

        for name in targets:
            info = apps.get(name, {})
            inst = manifest["installed"][name]
            st = self.app_status(name)
            install_path = st["path"]
            full_path = self.project_dir / install_path
            track = st["policy"]["track"]

            if not full_path.exists():
                skipped.append((name, "path missing"))
                continue

            if track == TRACK_LOCAL:
                skipped.append((name, "track=local (yours)"))
                continue
            if track == TRACK_PINNED:
                pin = st["policy"].get("commit", inst.get("version", "?"))
                skipped.append((name, f"track=pinned @ {pin}"))
                continue

            ok, reason = self.guard(name, force=force)
            if not ok:
                skipped.append((name, f"{reason} — backup & --force to override"))
                continue
            if reason:
                print(f"  {name}: {reason}")

            ref = st["want_ref"]
            print(f"Updating {info.get('name', name)} ({track} → {ref})...")
            if dry_run:
                updated += 1
                continue

            r = self._sub_git(install_path, "fetch", "origin")
            if r.returncode != 0:
                skipped.append((name, "fetch failed"))
                continue

            if track == TRACK_BRANCH:
                # Follow the branch the user parked this app on: fast-forward
                # in place, never check something else out.
                if st["git"]["branch"] != ref:
                    skipped.append((name, f"on {st['git']['branch']}, "
                                          f"config says {ref}"))
                    continue
                r = self._sub_git(install_path, "merge", "--ff-only",
                                  f"origin/{ref}")
                if r.returncode != 0:
                    skipped.append((name, "not fast-forwardable "
                                          "(diverged from origin)"))
                    continue
            else:
                checkout_ref = (f"origin/{ref}"
                                if not ref.startswith(("origin/", "refs/"))
                                and len(ref) < 12
                                else ref)
                r = self._sub_git(install_path, "checkout", checkout_ref)
                if r.returncode != 0:
                    skipped.append((name, f"checkout {checkout_ref} failed"))
                    continue

            self._git("add", install_path, check=False)
            commit = self._get_submodule_commit(install_path)
            old_commit = inst.get("version", "?")
            inst["version"] = commit
            inst["ref"] = ref
            inst["updated_at"] = datetime.now(timezone.utc).isoformat()
            print(f"  {old_commit} -> {commit}")
            updated += 1

        if not dry_run:
            self._save_manifest(manifest)

        if skipped:
            print("\n  Skipped:")
            for name, reason in skipped:
                print(f"    {name:<16} {reason}")
        if updated and not dry_run:
            self._print_next_steps()

    def status(self, app_name: str = None):
        """Report intent vs observed state for installed apps."""
        manifest = self._load_manifest()
        targets = ([app_name] if app_name
                   else list(manifest.get("installed", {}).keys()))
        if not targets:
            print("No apps installed.")
            return

        print(f"\n  {'app':<16} {'track':<9} {'state':<34} backups")
        print("  " + "-" * 72)
        for name in targets:
            st = self.app_status(name)
            n_backups = len(self.list_backups(name))
            mark = "!" if st["blocking"] else ("~" if st["protected"] else " ")
            print(f"{mark} {name:<16} {st['policy']['track']:<9} "
                  f"{self.describe_status(st):<34} "
                  f"{n_backups if n_backups else ''}")
        print("\n  ! = blocked for updates   ~ = protected by policy\n")

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
            elif exists_on_disk and already_in_manifest:
                # The manifest records the commit that was installed, but every
                # cross-repo bump (git submodule update, a manual checkout) moves
                # the submodule without touching apps.json — so the recorded
                # version drifts and `list` reports a commit that has not been
                # checked out for months. Re-read it from git; that is the whole
                # point of a sync command.
                commit = self._get_submodule_commit(install_path)
                branch = self._get_submodule_branch(install_path)
                inst = manifest["installed"][app_id]
                changed = False
                if commit != "unknown" and commit != inst.get("version"):
                    print(f"  ~ {app_id} ({inst.get('version', '?')} -> {commit})")
                    inst["version"] = commit
                    changed = True
                # A stale ref is worse than a stale version: `update` checks out
                # origin/<ref>, so a manifest still claiming "main" for an app
                # living on master fails outright, and for an app parked on a
                # feature branch it silently drags the build onto main.
                if branch and branch != inst.get("ref"):
                    print(f"  ~ {app_id} ref {inst.get('ref', '?')} -> {branch}")
                    inst["ref"] = branch
                    changed = True
                if changed:
                    inst["updated_at"] = datetime.now(timezone.utc).isoformat()
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
        elif self.config.platform == "pc":
            print(f"\n  Next: rm -rf build && cmake -B build -G Ninja && cmake --build build")
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
    update_cmd.add_argument("--force", action="store_true",
                            help="Update despite local work (backs up first)")
    update_cmd.add_argument("--dry-run", action="store_true",
                            help="Show what would happen, change nothing")

    status_cmd = sub.add_parser("status",
                                help="Show track policy vs git state per app")
    status_cmd.add_argument("app", nargs="?", help="App name")

    track_cmd = sub.add_parser("track", help="Set an app's track policy")
    track_cmd.add_argument("app", help="App name")
    track_cmd.add_argument("mode", choices=list(TRACK_MODES))
    track_cmd.add_argument("--ref", default=None,
                           help="Branch for track=branch")
    track_cmd.add_argument("--commit", default=None,
                           help="Commit for track=pinned")
    track_cmd.add_argument("--local", action="store_true",
                           help="Write to crosspad.local.json (not shared)")

    backup_cmd = sub.add_parser("backup", help="Snapshot an app's local work")
    backup_cmd.add_argument("app", help="App name")

    restore_cmd = sub.add_parser("restore", help="Restore a backup")
    restore_cmd.add_argument("app", help="App name")
    restore_cmd.add_argument("stamp", nargs="?",
                             help="Backup timestamp (default: newest)")
    restore_cmd.add_argument("--list", action="store_true",
                             help="List available backups")

    sub.add_parser("device",
                   help="Ask a connected CrossPad what it was built from")
    sub.add_parser("config-init",
                   help=f"Create {CONFIG_FILE} from the current state")

    cfg_cmd = sub.add_parser("config", help="Show or set compile-time features")
    cfg_cmd.add_argument("flag", nargs="?", help="Flag name")
    cfg_cmd.add_argument("value", nargs="?",
                         help="New value (on/off or enum value)")
    cfg_cmd.add_argument("--local", action="store_true",
                         help=f"Write to {LOCAL_CONFIG_FILE}")
    cfg_cmd.add_argument("--gen", action="store_true",
                         help="Regenerate .crosspad/build_flags.*")

    prof_cmd = sub.add_parser("profile", help="Named build recipes")
    prof_cmd.add_argument("action",
                          choices=["list", "show", "apply", "save"])
    prof_cmd.add_argument("name", nargs="?", help="Profile name")
    prof_cmd.add_argument("--remove-extra", action="store_true",
                          help="Remove installed apps the profile omits")
    prof_cmd.add_argument("--description", default="",
                          help="Description when saving")
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
        mgr.update(app_name=args.app, update_all=args.all,
                   force=args.force, dry_run=args.dry_run)
    elif args.command == "status":
        mgr.status(args.app)
    elif args.command == "track":
        mgr.ensure_config(quiet=True)
        mgr.set_app_policy(args.app, args.mode, ref=args.ref,
                           commit=args.commit, local=args.local)
        where = LOCAL_CONFIG_FILE if args.local else CONFIG_FILE
        print(f"{args.app}: track={args.mode}"
              f"{' ref=' + args.ref if args.ref else ''} -> {where}")
    elif args.command == "backup":
        dest = mgr.backup_app(args.app)
        print(f"Backup: {dest}" if dest else f"Nothing to back up for '{args.app}'.")
    elif args.command == "restore":
        if args.list:
            stamps = mgr.list_backups(args.app)
            print("\n".join(f"  {t}" for t in stamps) if stamps
                  else f"No backups for '{args.app}'.")
        else:
            mgr.restore_backup(args.app, args.stamp)
    elif args.command == "device":
        report = mgr.device_diff()
        if not report.get("ok"):
            print(f"Device: {report.get('error')}")
            sys.exit(1)
        print(f"\n  Device on {report['port']}\n")
        print(f"  {'component':<24}{'device':<12}{'repo':<12}ref")
        for row in report["rows"]:
            mark = " " if row["match"] else "!"
            dirty = " *" if row["device_dirty"] else ""
            print(f"{mark} {row['component']:<24}{row['device_commit']:<12}"
                  f"{row['local_commit']:<12}{row['device_ref']}{dirty}")
        stale = report.get("stale", [])
        if stale:
            print(f"\n  ! {len(stale)} component(s) differ from this "
                  f"checkout — the device is not running it\n")
            sys.exit(2)
        print("\n  Device matches this checkout.\n")
    elif args.command == "config-init":
        mgr.ensure_config()
    elif args.command == "config":
        _config_cli(mgr, args)
    elif args.command == "profile":
        _profile_cli(mgr, args)
    elif args.command == "sync":
        mgr.sync()
        mgr.ensure_config(quiet=True)
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


def _config_cli(mgr: "AppManager", args):
    schema = mgr.load_feature_schema()
    flags = {f["name"]: f for f in schema.get("flags", [])}

    if args.flag:
        if args.flag not in flags:
            print(f"Unknown flag '{args.flag}'. Known: {', '.join(flags)}")
            sys.exit(1)
        if args.value is None:
            print(f"{args.flag} = {mgr.feature_values().get(args.flag)}")
            return
        flag = flags[args.flag]
        if flag.get("type") == "bool":
            value = args.value.lower() in ("1", "on", "true", "yes", "y")
        else:
            allowed = [v["value"] for v in flag.get("values", [])]
            if allowed and args.value not in allowed:
                print(f"Invalid value. Allowed: {', '.join(allowed)}")
                sys.exit(1)
            value = args.value
        mgr.ensure_config(quiet=True)
        mgr.set_feature(args.flag, value, local=args.local)
        print(f"{args.flag} = {value}")
    else:
        values = mgr.feature_values()
        if not flags:
            print(f"No {FEATURES_SCHEMA} found "
                  f"(is crosspad-core checked out?)")
            return
        groups = {g["id"]: g["title"] for g in schema.get("groups", [])}
        current_group = None
        for name, flag in flags.items():
            grp = flag.get("group", "other")
            if grp != current_group:
                current_group = grp
                print(f"\n  {groups.get(grp, grp)}")
            value = values.get(name)
            default = flag.get("default")
            managed = mgr._flag_managed_elsewhere(flag)
            # A managed flag is never "overridden by us" — its value comes from
            # the other build system, so the override marker would misattribute it.
            mark = " " if value == default or managed else "*"
            note = f"   [{managed}-managed on {mgr.config.platform}]" if managed else ""
            print(f"  {mark} {name:<28} {str(value):<28}{note}")
        print("\n  * = overridden in the project config\n")

    for problem in mgr.validate_features():
        print(f"  warning: {problem}")
    if args.gen or args.flag:
        gen = mgr.generate_build_flags()
        print(f"  wrote {gen['cmake']} ({len(gen['defs'])} override(s), "
              f"set {gen['hash']})")


def _profile_cli(mgr: "AppManager", args):
    if args.action == "list":
        names = mgr.list_profiles()
        if not names:
            print(f"No profiles in {PROFILE_DIR}/.")
            return
        for name in names:
            prof = mgr.load_profile(name) or {}
            print(f"  {name:<18} {prof.get('description', '')}")
        return

    if not args.name:
        print("Specify a profile name.")
        sys.exit(1)

    if args.action == "save":
        path = mgr.save_profile(args.name, args.description)
        print(f"Saved {path}")
        return

    plan = mgr.profile_plan(args.name)
    if plan is None:
        print(f"No profile '{args.name}'. Available: "
              f"{', '.join(mgr.list_profiles()) or 'none'}")
        sys.exit(1)

    print(f"\nProfile '{args.name}': {plan['profile'].get('description', '')}")
    for flag, old, new in plan["features"]:
        print(f"  flag    {flag}: {old} -> {new}")
    for app_id, ref in plan["install"]:
        print(f"  install {app_id} ({ref})")
    for app_id, old, new in plan["retrack"]:
        print(f"  track   {app_id}: {old} -> {new}")
    for app_id in plan["remove"]:
        print(f"  extra   {app_id} "
              f"{'(will be removed)' if args.remove_extra else '(kept)'}")
    for app_id, reason in plan["protected"]:
        print(f"  keep    {app_id} — {reason}")
    if not any((plan["features"], plan["install"], plan["retrack"],
                plan["remove"])):
        print("  already matches this profile")

    if args.action == "apply":
        print()
        mgr.apply_profile(args.name, remove_extra=args.remove_extra)


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


def _read_raw_char() -> str:
    """One character straight off the stdin fd, decoding UTF-8 continuations.

    Deliberately not sys.stdin.read(): that wrapper buffers, and anything it
    pulls in ahead of time becomes invisible to the select() below, which is
    how a well-formed arrow key ends up reported as a bare Esc followed by two
    stray letters.
    """
    fd = sys.stdin.fileno()
    b = os.read(fd, 1)
    if not b:
        return ""
    first = b[0]
    if first < 0x80:
        return chr(first)
    extra = (1 if first >= 0xC0 else 0) + (1 if first >= 0xE0 else 0) \
            + (1 if first >= 0xF0 else 0)
    for _ in range(extra):
        b += os.read(fd, 1)
    return b.decode("utf-8", errors="replace")


def _read_within(timeout: float) -> str | None:
    """Next character, or None if the terminal stays quiet for `timeout`.

    Only meaningful while stdin is in raw mode; used to tell a bare Esc apart
    from the start of a cursor-key escape sequence.
    """
    try:
        import select
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            return None
        return _read_raw_char()
    except (ImportError, OSError, ValueError):
        return _read_raw_char()


def _read_key() -> str:
    """Read a single keypress, return normalized key name."""
    try:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = _read_raw_char()
            if ch == "\x1b":
                # Escape starts both a bare Esc keypress and every arrow /
                # navigation sequence. Reading a fixed two more bytes blocked
                # forever on a lone Esc — which the menus advertise as "cancel"
                # — so wait briefly for a continuation instead and treat a
                # silent terminal as the bare key.
                nxt = _read_within(0.05)
                if nxt is None:
                    return "esc"
                # CSI ("\x1b[") and SS3 ("\x1bO", application cursor mode)
                # both prefix the cursor keys.
                if nxt not in ("[", "O"):
                    return "esc"
                code = _read_within(0.05)
                if code is None:
                    return "esc"
                simple = {"A": "up", "B": "down", "C": "right", "D": "left",
                          "H": "home", "F": "end"}
                if code in simple:
                    return simple[code]
                if code.isdigit():
                    # Numeric CSI forms: 5~ PgUp, 6~ PgDn, 1~/7~ Home, 4~/8~ End.
                    tail = _read_within(0.05)
                    while tail is not None and tail.isdigit():
                        code += tail
                        tail = _read_within(0.05)
                    numeric = {"5": "pgup", "6": "pgdn", "1": "home",
                               "7": "home", "4": "end", "8": "end"}
                    return numeric.get(code, "esc")
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
        self._toast = ""
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
            inner = f"CrossPad App Manager   ·   {plat}"
            box_w = max(len(inner) + 6, 50)
            if box_w > w - 4:
                box_w = w - 4
            pad_total = box_w - len(inner)
            lp = pad_total // 2
            rp = pad_total - lp

            _w(f"\n  {_C.BCYAN}╭{'─' * box_w}╮{_C.RST}\n")
            _w(f"  {_C.BCYAN}│{_C.RST}"
               f"{' ' * lp}{_C.BWHITE}CrossPad App Manager{_C.RST}"
               f"   {_C.GRAY}·{_C.RST}   "
               f"{_C.BCYAN}{plat}{_C.RST}"
               f"{' ' * rp}{_C.BCYAN}│{_C.RST}\n")
            _w(f"  {_C.BCYAN}╰{'─' * box_w}╯{_C.RST}\n")

            if self._toast:
                _w(f"\n   {_C.BGREEN}✓{_C.RST} {self._toast}\n")
                self._toast = ""

            # -- stats: project, registry, feature flags, build --
            inst_c, total_c = self._compatible_count()
            cache_age = self.mgr.get_cache_age()
            cache_str = self._fmt_age(cache_age) if cache_age >= 0 else "none"
            proj = self.mgr.project_dir.name
            plat_label = plat.upper().replace("-", " ")

            overrides = self.mgr.feature_overrides()
            flags_str = (f"{len(overrides)} override(s) "
                         f"· {self.mgr.flags_hash()}" if overrides
                         else "stock")
            build = self.mgr.get_build_info()
            if not build.get("exists"):
                build_str = f"{_C.GRAY}not built{_C.RST}"
            elif self.mgr.build_flags_stale():
                build_str = f"{_C.BYELLOW}flags changed{_C.RST}"
            elif build.get("stale"):
                build_str = f"{_C.BYELLOW}sources newer{_C.RST}"
            else:
                build_str = (f"{_C.BGREEN}current{_C.RST} "
                             f"{_C.GRAY}({self._fmt_age(build['age_seconds'])})"
                             f"{_C.RST}")

            _w(f"\n   {_C.GRAY}Platform{_C.RST}    "
               f"{_C.BWHITE}{plat_label}{_C.RST}")
            _w(f"{'':>10}{_C.GRAY}Project{_C.RST}    "
               f"{_C.BWHITE}{proj}{_C.RST}\n")
            _w(f"   {_C.GRAY}Installed{_C.RST}   "
               f"{_C.BWHITE}{inst_c}{_C.RST}"
               f"{_C.GRAY}/{total_c} compatible{_C.RST}")
            _w(f"{'':>4}{_C.GRAY}Registry{_C.RST}   "
               f"{_C.BWHITE}{cache_str}{_C.RST}\n")
            _w(f"   {_C.GRAY}Features{_C.RST}    "
               f"{_C.BWHITE}{flags_str}{_C.RST}")
            pad = max(20 - len(flags_str), 2)
            _w(f"{'':>{pad}}{_C.GRAY}Build{_C.RST}      {build_str}\n")

            # -- installed apps, with ownership state --
            if self._installed:
                blocked = 0
                self._section("Installed Apps")
                for app_id in self._installed:
                    st = self.mgr.app_status(app_id)
                    info = self._apps.get(app_id, {})
                    name = info.get("name", app_id)
                    track = st["policy"]["track"]
                    if st["blocking"]:
                        dot, col = "●", _C.BYELLOW
                        blocked += 1
                    elif st["protected"]:
                        dot, col = "✋", _C.BCYAN
                    else:
                        dot, col = "●", _C.BGREEN
                    _w(f"   {col}{dot}{_C.RST} "
                       f"{name:<16} "
                       f"{_C.GRAY}{track:<9}{_C.RST}"
                       f"{_C.DIM}{self.mgr.describe_status(st)}{_C.RST}\n")
                if blocked:
                    _w(f"\n   {_C.BYELLOW}{blocked} app(s) carry local work — "
                       f"updates skip them.{_C.RST}\n")
            else:
                _w(f"\n   {_C.GRAY}No apps installed yet. "
                   f"Press {_C.BYELLOW}b{_C.RST}{_C.GRAY} to browse."
                   f"{_C.RST}\n")

            # -- quick actions, grouped so the row stays readable --
            self._section("Quick Actions")
            groups = [
                ("apps", [("B", "Browse"), ("U", "Update"),
                          ("W", "Workspace")]),
                ("build", [("C", "Configure"), ("P", "Profiles"),
                           ("F", "Build & Run" if plat == "pc"
                            else "Build & Flash")]),
                ("device", [("O", "Run Sim" if plat == "pc" else "OTA Flash"),
                            ("D", "Device"), ("H", "Health"),
                            ("T", "Tools"), ("Q", "Quit")]),
            ]
            for label, entries in groups:
                row = f"   {_C.GRAY}{label:<7}{_C.RST}"
                for key, text in entries:
                    row += f"{_C.BCYAN}[{key}]{_C.RST} {text:<14}"
                _w(row + "\n")

            key = _read_key()
            if key in ("q", "ctrl-c", "esc"):
                break
            elif key == "b":
                self._browse()
                self._reload()
            elif key == "u":
                self._update_flow()
                self._reload()
            elif key == "w":
                self._workspace()
                self._reload()
            elif key == "c":
                self._configure()
            elif key == "p":
                self._profiles()
                self._reload()
            elif key == "d":
                self._device()
            elif key == "h":
                self._health()
            elif key == "f":
                self._build_flash()
            elif key == "o":
                self._quick_ota()
            elif key == "t":
                self._dev_tools()
                self._reload()

    # -- Device ---------------------------------------------------------------

    def _device(self):
        """What the connected CrossPad reports it was built from, vs this repo.

        The manifest says what should be installed; this says what is actually
        running on the desk. When the two disagree, the firmware is older than
        the checkout — the single most common source of "but I fixed that".
        """
        report = None
        while True:
            _clear()
            self._header("Device", "APP_VERSIONS over CDC")

            if report is None:
                _w(f"\n   {_C.GRAY}Querying device...{_C.RST}\n")
                report = self.mgr.device_diff()
                continue

            if not report.get("ok"):
                _w(f"\n   {_C.BYELLOW}⚠{_C.RST} {report.get('error')}\n")
                if self.config.platform != "pc":
                    _w(f"\n   {_C.GRAY}A device in USB audio mode exposes no "
                       f"CDC. Switch it back with\n   the SysEx "
                       f"F0 7D 1B 00 F7 on its own MIDI port.{_C.RST}\n")
                self._footer("[r] retry   q back")
            else:
                _w(f"\n   {_C.GRAY}Port{_C.RST}   {report['port']}\n\n")
                _w(f"   {_C.GRAY}{'component':<24}{'device':<12}"
                   f"{'repo':<12}{'ref':<16}{_C.RST}\n")
                for row in report["rows"]:
                    if row["match"]:
                        mark, col = "✓", _C.BGREEN
                    else:
                        mark, col = "≠", _C.BYELLOW
                    dirty = f"{_C.BYELLOW}*{_C.RST}" if row["device_dirty"] else ""
                    _w(f" {col}{mark}{_C.RST} {row['component']:<24}"
                       f"{row['device_commit']:<12}"
                       f"{row['local_commit']:<12}"
                       f"{_C.GRAY}{row['device_ref']:<16}{_C.RST}{dirty}\n")

                stale = report.get("stale", [])
                if stale:
                    _w(f"\n   {_C.BYELLOW}{len(stale)} component(s) differ — "
                       f"the device is not running this checkout.{_C.RST}\n")
                    _w(f"   {_C.GRAY}Reflash: press o (OTA) from the "
                       f"dashboard.{_C.RST}\n")
                else:
                    _w(f"\n   {_C.BGREEN}Device matches this checkout.{_C.RST}\n")
                if any(r["device_dirty"] for r in report["rows"]):
                    _w(f"   {_C.GRAY}* built from a dirty worktree — the commit "
                       f"alone does not describe that binary.{_C.RST}\n")
                self._footer("[r] refresh   q back")

            key = _read_key()
            if key in ("q", "esc", "ctrl-c"):
                return
            if key == "r":
                report = None

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
        _w(f"\n  Checking {len(self._installed)} app(s)...\n\n")

        # Show what the guard will do before touching anything — an update that
        # silently skips half the apps is worse than one that says so up front.
        blocked = []
        for app_id in self._installed:
            st = self.mgr.app_status(app_id)
            if st["protected"]:
                _w(f"   {_C.BCYAN}\u270b{_C.RST} {app_id:<16}"
                   f"{_C.GRAY}protected: track="
                   f"{st['policy']['track']}{_C.RST}\n")
            elif st["blocking"]:
                blocked.append(app_id)
                _w(f"   {_C.BYELLOW}\u25cf{_C.RST} {app_id:<16}"
                   f"{_C.YELLOW}local work: "
                   f"{', '.join(st['blocking'])}{_C.RST}\n")
            else:
                _w(f"   {_C.BGREEN}\u25cf{_C.RST} {app_id:<16}"
                   f"{_C.GRAY}ready{_C.RST}\n")

        force = False
        if blocked:
            _w(f"\n  {len(blocked)} app(s) carry local work.\n")
            _show_cursor()
            force = _confirm("Back them up and update anyway?")
            _hide_cursor()

        _w("\n")
        _show_cursor()
        self.mgr.update(update_all=True, force=force)
        _hide_cursor()
        _pause()

    # -- Workspace ------------------------------------------------------------

    def _workspace(self):
        """Per-app ownership: track policy, git state, backup / restore.

        This is the screen that answers "is this app mine or the registry's?"
        before anything destructive runs.
        """
        cursor = 0
        statuses = []

        def refresh():
            nonlocal statuses
            statuses = [self.mgr.app_status(a) for a in self._installed]

        refresh()

        while True:
            if not statuses:
                _clear()
                _w(f"\n  {_C.GRAY}No apps installed.{_C.RST}\n")
                _pause()
                return

            _clear()
            self._header("Workspace",
                         f"{len(statuses)} app(s)   ·   "
                         f"{CONFIG_FILE}")
            if self._toast:
                _w(f"\n   {_C.BGREEN}✓{_C.RST} {self._toast}\n")
                self._toast = ""
            _w("\n")

            for i, st in enumerate(statuses):
                name = st["app"]
                track = st["policy"]["track"]
                if st["blocking"]:
                    dot, col = "●", _C.BYELLOW
                elif st["protected"]:
                    dot, col = "✋", _C.BCYAN
                else:
                    dot, col = "●", _C.BGREEN
                marker = f"{_C.BYELLOW}>{_C.RST}" if i == cursor else " "
                nb = len(self.mgr.list_backups(name))
                _w(f"  {marker} {col}{dot}{_C.RST} {name:<16}"
                   f"{_C.GRAY}track={_C.RST}{track:<9} "
                   f"{self.mgr.describe_status(st):<30} "
                   f"{_C.DIM}{('bk:' + str(nb)) if nb else ''}{_C.RST}\n")
                if i == cursor and st["blocking"]:
                    _w(f"      {_C.YELLOW}blocked: "
                       f"{', '.join(st['blocking'])}{_C.RST}\n")

            self._section("Legend")
            _w(f"   {_C.BGREEN}●{_C.RST} clean   "
               f"{_C.BYELLOW}●{_C.RST} local work (updates blocked)   "
               f"{_C.BCYAN}✋{_C.RST} protected by policy\n")

            self._footer("↑↓ navigate   [m] track mode   "
                         "[b] backup   [r] restore   [p] park WIP   "
                         "[enter] details   q back")

            key = _read_key()
            if key in ("q", "esc", "ctrl-c"):
                return
            elif key == "up":
                cursor = (cursor - 1) % len(statuses)
            elif key == "down":
                cursor = (cursor + 1) % len(statuses)
            elif key == "m":
                self._track_mode_flow(statuses[cursor])
                refresh()
            elif key == "b":
                app = statuses[cursor]["app"]
                dest = self.mgr.backup_app(app)
                self._toast = (f"{app}: backed up to "
                               f"{Path(dest).relative_to(self.mgr.project_dir)}"
                               if dest else f"{app}: nothing to back up")
                refresh()
            elif key == "r":
                self._restore_flow(statuses[cursor]["app"])
                refresh()
            elif key == "p":
                app = statuses[cursor]["app"]
                before = statuses[cursor]["git"]["branch"]
                ok = self.mgr.park_wip(app)
                after = self.mgr.app_status(app)["git"]["branch"]
                self._toast = (f"{app}: parked on {after}" if ok and after != before
                               else f"{app}: nothing to park" if ok
                               else f"{app}: could not park WIP")
                refresh()
            elif key == "enter":
                self._workspace_detail(statuses[cursor])
                refresh()

    def _track_mode_flow(self, st: dict):
        app = st["app"]
        modes = [
            (TRACK_REGISTRY, "Follow the registry ref (fast-forward only)"),
            (TRACK_BRANCH, "Follow a branch of yours; never switched away"),
            (TRACK_PINNED, "Freeze at the current commit"),
            (TRACK_LOCAL, "Hands off — the manager never touches it"),
        ]
        cur = st["policy"]["track"]
        labels = [f"{m}{'  (current)' if m == cur else ''}" for m, _ in modes]
        idx = _menu_select(f"Track mode — {app}", labels,
                           [d for _, d in modes])
        if idx < 0:
            return
        mode = modes[idx][0]
        ref = commit = None
        if mode == TRACK_BRANCH:
            _show_cursor()
            ref = _text_input("Branch",
                              st["git"]["branch"] or st["want_ref"])
            _hide_cursor()
            if not ref:
                return
        elif mode == TRACK_PINNED:
            commit = st["git"]["head"]
        self.mgr.ensure_config(quiet=True)
        self.mgr.set_app_policy(app, mode, ref=ref, commit=commit)
        _clear()
        _w(f"\n  {app}: track={mode}"
           f"{' ref=' + ref if ref else ''}"
           f"{' @ ' + commit if commit else ''}\n"
           f"  written to {CONFIG_FILE}\n")
        _pause()

    def _restore_flow(self, app: str):
        stamps = self.mgr.list_backups(app)
        if not stamps:
            _clear()
            _w(f"\n  {_C.GRAY}No backups for {app}.{_C.RST}\n")
            _pause()
            return
        descs = []
        for s in stamps:
            meta_path = self.mgr.backup_dir(app) / s / "meta.json"
            try:
                meta = json.loads(meta_path.read_text())
                descs.append(f"{meta.get('branch') or 'detached'} @ "
                             f"{meta.get('head')}   "
                             f"{', '.join(meta.get('flags', []))}")
            except (OSError, ValueError):
                descs.append("")
        idx = _menu_select(f"Restore backup — {app}", stamps, descs)
        if idx < 0:
            return
        _clear()
        _show_cursor()
        self.mgr.restore_backup(app, stamps[idx])
        _hide_cursor()
        _pause()

    def _workspace_detail(self, st: dict):
        app = st["app"]
        while True:
            _clear()
            self._header(f"Workspace — {app}")
            git = st["git"]
            rows = [
                ("Track", st["policy"]["track"]),
                ("Wanted ref", st["want_ref"]),
                ("Branch", git["branch"] or f"detached @ {git['head']}"),
                ("HEAD", git["head"] or "?"),
                ("Upstream", git["upstream"] or "none"),
                ("Ahead / behind", f"{git['ahead']} / {git['behind']}"),
                ("Dirty files", str(git["dirty"])),
                ("Untracked", str(git["untracked"])),
                ("Stashes", str(git["stashes"])),
                ("Origin", git["origin"] or "?"),
                ("Flags", ", ".join(st["flags"]) or "clean"),
                ("Backups", str(len(self.mgr.list_backups(app)))),
            ]
            _w("\n")
            for label, value in rows:
                _w(f"   {_C.GRAY}{label:<16}{_C.RST}{value}\n")

            log = self.mgr.get_app_git_log(st["path"], 5)
            if log:
                self._section("Recent commits")
                for line in log:
                    _w(f"   {_C.DIM}{line}{_C.RST}\n")

            self._footer("[m] track mode   [b] backup   [r] restore   "
                         "[p] park WIP   q back")
            key = _read_key()
            if key in ("q", "esc", "ctrl-c"):
                return
            elif key == "m":
                self._track_mode_flow(st)
            elif key == "b":
                _clear()
                dest = self.mgr.backup_app(app)
                _w(f"\n  {'Backup: ' + dest if dest else 'Nothing to back up.'}\n")
                _pause()
            elif key == "r":
                self._restore_flow(app)
            elif key == "p":
                _clear()
                self.mgr.park_wip(app)
                _pause()
            st = self.mgr.app_status(app)

    # -- Configure (compile-time features) ------------------------------------

    def _configure(self):
        """menuconfig-style feature tree driven by features.schema.json."""
        schema = self.mgr.load_feature_schema()
        flags = schema.get("flags", [])
        if not flags:
            _clear()
            _w(f"\n  {_C.GRAY}No {FEATURES_SCHEMA} found — is crosspad-core "
               f"checked out?{_C.RST}\n")
            _pause()
            return

        titles = {g["id"]: g["title"] for g in schema.get("groups", [])}
        cursor = 0

        while True:
            values = self.mgr.feature_values()
            problems = self.mgr.validate_features()
            gen_defs = self.mgr.feature_overrides()

            _clear()
            self._header("Configure — compile-time features",
                         f"{len(gen_defs)} override(s)  ·  "
                         f"set {self.mgr.flags_hash()}")
            _w("\n")

            group = None
            for i, flag in enumerate(flags):
                grp = flag.get("group", "other")
                if grp != group:
                    group = grp
                    _w(f"\n   {_C.GRAY}── {titles.get(grp, grp)}{_C.RST}\n")
                name = flag["name"]
                value = values.get(name)
                default = flag.get("default")
                managed = self.mgr._flag_managed_elsewhere(flag)

                if flag.get("type") == "bool":
                    shown = f"[{'*' if value else ' '}]"
                else:
                    label = name
                    shown = str(value)
                    for v in flag.get("values", []):
                        if v["value"] == value:
                            shown = v.get("label", value)
                            break

                marker = f"{_C.BYELLOW}>{_C.RST}" if i == cursor else " "
                col = _C.BWHITE if value != default else _C.RST
                dim = f"{_C.DIM}(managed by {managed}){_C.RST}" if managed else (
                    f"{_C.BYELLOW}*{_C.RST}" if value != default else " ")
                if managed:
                    col = _C.RST
                _w(f"  {marker} {name:<28}{col}{shown:<32}{_C.RST}{dim}\n")

            if 0 <= cursor < len(flags):
                help_text = flags[cursor].get("help", "")
                if help_text:
                    _w(f"\n   {_C.GRAY}{help_text}{_C.RST}\n")

            if problems:
                _w("\n")
                for p in problems:
                    _w(f"   {_C.BYELLOW}⚠ {p}{_C.RST}\n")

            self._footer("↑↓ navigate   space/enter toggle   "
                         "[d] default   [g] generate flags   "
                         "[s] save as profile   q back")

            key = _read_key()
            if key in ("q", "esc", "ctrl-c"):
                self.mgr.generate_build_flags()
                return
            elif key == "up":
                cursor = (cursor - 1) % len(flags)
            elif key == "down":
                cursor = (cursor + 1) % len(flags)
            elif key in ("enter", " "):
                self._toggle_flag(flags[cursor], values)
            elif key == "d":
                flag = flags[cursor]
                self.mgr.ensure_config(quiet=True)
                self.mgr.set_feature(flag["name"], flag.get("default"))
            elif key == "g":
                _clear()
                gen = self.mgr.generate_build_flags()
                _w(f"\n  {gen['cmake']}\n  {gen['ini']}\n\n"
                   f"  {len(gen['defs'])} override(s), set {gen['hash']}\n")
                for d in gen["defs"]:
                    _w(f"    -D{d}\n")
                if self.config.platform == "esp-idf":
                    _w(f"\n  {_C.GRAY}A changed flag set needs "
                       f"idf.py fullclean.{_C.RST}\n")
                _pause()
            elif key == "s":
                self._save_profile_flow()

    def _toggle_flag(self, flag: dict, values: dict):
        name = flag["name"]
        if self.mgr._flag_managed_elsewhere(flag):
            _clear()
            _w(f"\n  {name} is managed by "
               f"{self.mgr._flag_managed_elsewhere(flag)} on "
               f"{self.config.platform} — change it there.\n")
            _pause()
            return
        self.mgr.ensure_config(quiet=True)
        if flag.get("type") == "bool":
            self.mgr.set_feature(name, not values.get(name))
            return
        options = flag.get("values", [])
        if not options:
            return
        labels = [v.get("label", v["value"]) for v in options]
        idx = _menu_select(name, labels, [v["value"] for v in options])
        if idx >= 0:
            self.mgr.set_feature(name, options[idx]["value"])

    # -- Profiles -------------------------------------------------------------

    def _profiles(self):
        while True:
            names = self.mgr.list_profiles()
            _clear()
            self._header("Profiles", f"{PROFILE_DIR}/")
            if not names:
                _w(f"\n  {_C.GRAY}No profiles yet. A profile is a recipe: "
                   f"board, feature flags and the app set.{_C.RST}\n")
                self._footer("[s] save current state as a profile   q back")
                key = _read_key()
                if key == "s":
                    self._save_profile_flow()
                    continue
                return

            items, descs = [], []
            for name in names:
                prof = self.mgr.load_profile(name) or {}
                items.append(name)
                descs.append(f"{prof.get('description', '')}   "
                             f"{len(prof.get('apps', {}))} app(s), "
                             f"{len(prof.get('features', {}))} flag(s)")
            idx = _menu_select("Profiles", items, descs)
            if idx < 0:
                return
            self._profile_detail(names[idx])

    def _profile_detail(self, name: str):
        plan = self.mgr.profile_plan(name)
        if plan is None:
            return
        _clear()
        self._header(f"Profile — {name}")
        prof = plan["profile"]
        _w(f"\n   {_C.GRAY}{prof.get('description', '')}{_C.RST}\n\n")

        empty = True
        for flag, old, new in plan["features"]:
            _w(f"   {_C.BYELLOW}flag{_C.RST}     {flag}: {old} → {new}\n")
            empty = False
        for app_id, ref in plan["install"]:
            _w(f"   {_C.BGREEN}install{_C.RST}  {app_id} ({ref})\n")
            empty = False
        for app_id, old, new in plan["retrack"]:
            _w(f"   {_C.BCYAN}track{_C.RST}    {app_id}: {old} → {new}\n")
            empty = False
        for app_id in plan["remove"]:
            _w(f"   {_C.GRAY}extra{_C.RST}    {app_id} (kept unless you "
               f"confirm removal)\n")
            empty = False
        for app_id, reason in plan["protected"]:
            _w(f"   {_C.BCYAN}✋{_C.RST}       {app_id} — {reason}\n")
        if empty:
            _w(f"   {_C.GRAY}Project already matches this profile.{_C.RST}\n")

        self._footer("[a] apply   [x] apply + remove extras   q back")
        key = _read_key()
        if key not in ("a", "x"):
            return
        _clear()
        _show_cursor()
        self.mgr.apply_profile(name, remove_extra=(key == "x"))
        _hide_cursor()
        _pause()
        self._reload()

    def _save_profile_flow(self):
        _clear()
        _show_cursor()
        name = _text_input("Profile name", "")
        desc = _text_input("Description", "") if name else None
        _hide_cursor()
        if not name:
            return
        path = self.mgr.save_profile(name, desc or "")
        _clear()
        _w(f"\n  Saved {path}\n")
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
        elif self.config.platform == "pc":
            # PC: "OTA" = run simulator directly
            _clear()
            self._header("Run Simulator")
            build = self.mgr.get_build_info()
            if not build["exists"]:
                _w(f"\n   {_C.BRED}\u2717 No binary found{_C.RST}\n")
                _w(f"   {_C.GRAY}Build the project first.{_C.RST}\n")
                self._footer("[b] Build now   q back")
                key = _read_key()
                if key == "b":
                    _clear()
                    self._header("Building...")
                    _show_cursor()
                    self.mgr.run_command(
                        "cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug "
                        "&& cmake --build build")
                    _hide_cursor()
                    _pause()
                return
            if build.get("stale"):
                _w(f"\n   {_C.BYELLOW}\u26a0 Sources modified "
                   f"since last build{_C.RST}\n")
            _w(f"\n   Launching {build['path']}...\n")
            _show_cursor()
            self.mgr.run_command(build["path"])
            _hide_cursor()
            _pause()
            return
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
        elif plat == "pc":
            commands = [
                ("Build (incremental)",
                 "cmake --build build"),
                ("Configure + Build",
                 "cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug && cmake --build build"),
                ("Clean + Build",
                 "rm -rf build && cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug && cmake --build build"),
                ("Run Simulator",
                 "bin/CrossPad"),
            ]
        else:
            commands = [
                ("Build",
                 "cmake --build build"),
                ("Clean + Build",
                 "rm -rf build && cmake -B build && cmake --build build"),
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

            # intent vs state: a policy that no longer matches the worktree is
            # the thing that silently breaks the next update
            drift = []
            for aid in self._installed:
                st = self.mgr.app_status(aid)
                if st["blocking"]:
                    drift.append(f"{aid} ({', '.join(st['blocking'])})")
            if drift:
                _w(f"   {_C.BYELLOW}⚠{_C.RST} Ownership"
                   f"     {len(drift)} protected: {', '.join(drift)}\n")
            else:
                _w(f"   {_C.BGREEN}✓{_C.RST} Ownership"
                   f"     no local work in the way\n")

            # feature flags vs what the last build used
            overrides = self.mgr.feature_overrides()
            if not overrides:
                _w(f"   {_C.BGREEN}✓{_C.RST} Features"
                   f"      stock (checked-in defaults)\n")
            elif self.mgr.build_flags_stale():
                _w(f"   {_C.BYELLOW}⚠{_C.RST} Features"
                   f"      {len(overrides)} override(s), build predates them\n")
            else:
                _w(f"   {_C.BGREEN}✓{_C.RST} Features"
                   f"      {len(overrides)} override(s), "
                   f"set {self.mgr.flags_hash()}\n")

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
