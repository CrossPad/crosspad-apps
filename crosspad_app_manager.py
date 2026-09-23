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

from __future__ import annotations   # `X | None` annotations on Python 3.9 (ESP-IDF 5.5's floor)

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


MANAGER_VERSION = "1.1.0"    # CP Tools; shown in help and in support reports
REMOTE_REGISTRY_REPO = "CrossPad/crosspad-apps"
REMOTE_REGISTRY_PATH = "registry.json"
LOCAL_REGISTRY_FILE = "app-registry.json"
MANIFEST_FILE = "apps.json"           # state: what is on disk (machine-written)
CONFIG_FILE = "crosspad.config.json"  # intent: apps, track policy, features
LOCAL_CONFIG_FILE = "crosspad.local.json"  # personal overrides (gitignored)
WORK_ROOT = ".crosspad"               # generated + backup working data
BACKUP_ROOT = ".crosspad/backups"
AVAILABLE_FILE = ".crosspad/available.json"   # per-app fetch results, 1 h TTL
AVAILABLE_MAX_AGE_SECONDS = 3600
LAST_UPDATE_FILE = ".crosspad/last-update.json"
LAST_UPDATE_LOG = ".crosspad/last-update.log"
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
# The words the screens use for the same four modes; the CLI takes either.
TRACK_ALIASES = {"release": TRACK_REGISTRY, "development": TRACK_BRANCH,
                 "version": TRACK_PINNED, "mine": TRACK_LOCAL}

BLOCKING_FLAGS = ("dirty", "ahead", "branch-mismatch", "origin-mismatch")

RAW_BASE = "https://raw.githubusercontent.com"
API_BASE = "https://api.github.com"
# Where each platform's CI publishes ready-built firmware (tag → release).
RELEASE_REPOS = {"esp-idf": "CrossPad/platform-idf"}
RELEASE_FILE = ".crosspad/official-release.json"
FIRMWARE_DIR = ".crosspad/firmware"
HTTP_TIMEOUT_SECONDS = 15


class NetError(Exception):
    """A fetch that failed. `offline` says whether it reads as "no network"
    rather than "the server answered no" — a 404 is an answer, not an outage."""

    def __init__(self, message: str, offline: bool, cert: bool = False):
        super().__init__(message)
        self.offline = offline
        self.cert = cert


def http_get(url: str, timeout: float = HTTP_TIMEOUT_SECONDS) -> bytes:
    """GET a public URL with the standard library — no gh, no GitHub account.

    Reading a public registry, a public changelog or the manager itself needs
    nobody's sign-in; requiring `gh auth login` for it was the first wall a
    musician hit. HTTP(S)_PROXY from the environment is honoured by urllib.
    """
    import ssl
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "crosspad-apps"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise NetError(f"HTTP {e.code} for {url}", offline=False) from e
    except urllib.error.URLError as e:
        cert = isinstance(e.reason, ssl.SSLCertVerificationError)
        raise NetError(str(e.reason), offline=not cert, cert=cert) from e
    except (TimeoutError, OSError) as e:
        raise NetError(str(e), offline=True) from e


def raw_url(owner_repo: str, path: str, ref: str = "HEAD") -> str:
    return f"{RAW_BASE}/{owner_repo}/{ref}/{path}"


def owner_repo_of(url: str) -> str | None:
    """'https://github.com/CrossPad/crosspad-sampler.git' → 'CrossPad/crosspad-sampler'."""
    url = (url or "").strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    url = url.replace("git@github.com:", "https://github.com/")
    if "github.com/" not in url:
        return None
    parts = url.split("github.com/", 1)[1].split("/")
    return f"{parts[0]}/{parts[1]}" if len(parts) >= 2 and parts[0] and parts[1] else None


# == Versions & follow rules =================================================
#
# The UI never says "pinned": an app follows the latest release, follows the
# latest development, or stays on a version the user picked. These functions
# turn the config's track policy plus observed git facts into rows the screen
# draws — pure, so they are tested without git or a terminal.

import re as _re

RELEASE_TAG_RE = _re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def follow_rule(policy: dict) -> tuple[str, str]:
    """(rule, target): release | development <branch> | version <sha> | own."""
    track = policy.get("track", TRACK_REGISTRY)
    if track == TRACK_BRANCH:
        return "development", policy.get("ref", "")
    if track == TRACK_PINNED:
        return "version", policy.get("commit", "")
    if track == TRACK_LOCAL:
        return "own", ""
    return "release", ""


def parse_tag_lines(text: str) -> list[tuple[str, str]]:
    """`git for-each-ref --format='%(refname:short) %(creatordate:short)'` → [(tag, date)]."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        date = parts[1] if len(parts) > 1 and _re.match(r"\d{4}-\d{2}-\d{2}", parts[1]) else ""
        out.append((parts[0], date))
    return out


def newest_release(tags: list[tuple[str, str]]) -> str | None:
    """First semver tag in a newest-first list, or None."""
    for tag, _date in tags:
        if RELEASE_TAG_RE.match(tag):
            return tag
    return None


def _bare_version(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag


@dataclass
class VersionRow:
    kind: str          # release | development | version | other
    label: str
    target: str        # tag, branch or sha the row resolves to ("" for other)
    detail: str
    current: bool = False
    installed: bool = False
    recommended: bool = False


def version_rows(policy: dict, default_branch: str, installed_sha: str,
                 installed_tag: str | None, tags: list[tuple[str, str]],
                 dev_head: str, dev_behind: int) -> list[VersionRow]:
    rule, target = follow_rule(policy)
    newest = newest_release(tags)
    rows = []

    if newest:
        rel_detail = f"{_bare_version(newest):<8} auto-update"
        rel_target = newest
    else:
        rel_detail = f"no releases yet, uses {default_branch}"
        rel_target = default_branch
    rows.append(VersionRow("release", "Latest release", rel_target, rel_detail,
                           current=(rule == "release"), recommended=True))

    dev_note = f"{dev_head}, {dev_behind} commits newer" if dev_behind else f"{dev_head}, up to date"
    dev_branch = target if rule == "development" and target else default_branch
    rows.append(VersionRow("development", "Latest development", dev_branch,
                           f"{dev_branch:<8} {dev_note}",
                           current=(rule == "development")))

    for tag, date in tags:
        if not RELEASE_TAG_RE.match(tag):
            continue
        rows.append(VersionRow("version", _bare_version(tag), tag, date,
                               current=(rule == "version" and target == tag),
                               installed=(installed_tag == tag)))

    pinned_elsewhere = rule == "version" and target and target not in {t for t, _ in tags}
    if pinned_elsewhere:
        rows.append(VersionRow("other", target, target, "a commit you picked",
                               current=True, installed=(installed_sha == target)))
    else:
        rows.append(VersionRow("other", "Other commit…", "", ""))
    return rows


def app_row(status: dict, avail: dict | None, in_registry: bool) -> dict:
    """One dashboard line: what is installed, what is available, and a state."""
    git = status["git"]
    if not git.get("exists"):
        return {"state": "missing", "installed": "", "available": ""}
    if git.get("broken"):
        return {"state": "broken", "installed": "", "available": ""}
    rule, target = follow_rule(status["policy"])
    if rule == "own" or not in_registry:
        return {"state": "own", "installed": git.get("head") or "", "available": ""}
    tag = (avail or {}).get("installed_tag")
    installed = _bare_version(tag) if tag else (git.get("head") or "")
    if status["blocking"]:
        return {"state": "changes", "installed": installed, "available": ""}
    if not avail:
        return {"state": "current", "installed": installed, "available": ""}
    if rule == "release":
        newest = newest_release([tuple(t) for t in avail.get("tags", [])])
        if newest and avail.get("release_behind", 0) > 0:
            return {"state": "update", "installed": installed,
                    "available": _bare_version(newest)}
    elif rule == "development":
        if avail.get("dev_behind", 0) > 0:
            return {"state": "update", "installed": installed,
                    "available": f"{avail.get('default_branch', target)} {avail.get('dev_head', '')}".strip()}
    return {"state": "current", "installed": installed, "available": ""}


def _release_target(tags: list[tuple[str, str]], default_branch: str) -> str:
    newest = newest_release(tags)
    return newest if newest else f"origin/{default_branch}"


def parse_semver(text: str) -> tuple[int, int, int] | None:
    m = _re.match(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", text or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)


def version_satisfies(have: tuple | None, spec: str) -> bool:
    """`>=0.3.0`, `>1.2`, `^1.4`, `1.2.3`, `*` against a (major, minor, patch).
    Unknown `have` passes — a missing header is not a reason to refuse."""
    spec = (spec or "*").strip()
    if spec in ("*", "") or have is None:
        return True
    for part in spec.split(","):
        part = part.strip()
        op = _re.match(r"^(>=|<=|>|<|==|=|\^|~)?\s*(.*)$", part)
        want = parse_semver(op.group(2))
        if want is None:
            continue
        o = op.group(1) or "=="
        ok = {">=": have >= want, "<=": have <= want, ">": have > want, "<": have < want,
              "==": have == want, "=": have == want,
              "^": have >= want and have[0] == want[0],
              "~": have >= want and have[:2] == want[:2]}[o]
        if not ok:
            return False
    return True


def unmet_requirements(requires, have: dict) -> list[str]:
    """['core 1.20.0 is older than >=2.0.0'] for each requirement the checkout misses."""
    if isinstance(requires, list):
        requires = {r: "*" for r in requires}
    out = []
    for dep, spec in (requires or {}).items():
        v = have.get(dep)
        if not version_satisfies(v, spec):
            short = dep.replace("crosspad-", "")
            out.append(f"needs {short} {spec}, this project has "
                       f"{'.'.join(map(str, v))}")
    return out


def release_asset_names(tag: str, rev: str) -> dict:
    """The file names platform-idf's release job gives its outputs."""
    return {"image": f"CrossPad-{tag}-{rev}.bin",
            "components": f"CrossPad-{tag}-components.json",
            "sums": "SHA256SUMS.txt"}


def parse_sha256sums(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and len(parts[0]) == 64:
            out[parts[1].lstrip("*")] = parts[0].lower()
    return out


def checkout_matches_release(components: dict, local_heads: dict, dirty: list[str],
                             overrides: list[str]) -> tuple[bool, str]:
    """Is this checkout exactly what the release was built from?

    Only then may a downloaded image stand in for a build: same commit in
    every component the release lists, nothing uncommitted, no feature flag
    set differently. The reason names the first difference.
    """
    if overrides:
        return False, "feature flags differ from the defaults"
    if dirty:
        return False, f"{dirty[0]} has changes"
    for path, sha in components.items():
        local = local_heads.get(path)
        if not local:
            return False, f"{path} is not in this project"
        if not (local.startswith(sha) or sha.startswith(local)):
            return False, f"{path.rsplit('/', 1)[-1]} is on another version"
    return True, ""


CATALOG_REQUIRED = ("id", "name", "version", "description", "platforms")


def catalog_problems(meta: dict | None, visibility: str | None, owner_repo: str | None,
                     listed: list[str]) -> list[str]:
    """Why an app could not go into the catalog yet, in the author's terms."""
    if not owner_repo:
        return ["the app has no GitHub repository — publish it first (New app → public repo)"]
    if meta is None:
        return ["crosspad-app.json is missing from the app folder"]
    out = [f"crosspad-app.json has no \"{k}\"" for k in CATALOG_REQUIRED if not meta.get(k)]
    if meta.get("version") and not parse_semver(str(meta["version"])):
        out.append(f"version \"{meta['version']}\" is not like 1.2.3")
    if visibility and visibility.lower() != "public":
        out.append("the repository is private — other people could not install it")
    if owner_repo.lower() in (r.lower() for r in listed):
        out.append("it is already in the catalog")
    return out


def change_summary(status: dict, avail: dict | None) -> list[str]:
    """Commit subjects an update would bring to this app, newest first.

    Conventional-commit prefixes ("fix(sampler): ") are dropped — a musician
    reads "kit selector remembers the last kit", not the scope syntax.
    """
    if not avail:
        return []
    rule, _ = follow_rule(status["policy"])
    subjects = avail.get("release_log" if rule == "release" else "dev_log", []) \
        if rule in ("release", "development") else []
    return [_re.sub(r"^\w+(\([^)]*\))?!?:\s*", "", subj) for subj in subjects]


# == What's next ==============================================================

def whats_next(ctx: dict) -> dict:
    """The dashboard's first line. First matching rule wins."""
    if ctx.get("mismatch"):
        return {"line": f"The board runs {ctx['fw_rev']} firmware on a "
                        f"{ctx['board_rev']} board",
                "action": "update", "estimate": ctx.get("estimate")}
    if ctx.get("unfinished"):
        return {"line": f"The last update stopped at {ctx['unfinished']}",
                "action": "resume", "estimate": None}
    updates = ctx.get("updates") or []
    if updates:
        n = len(updates)
        return {"line": f"{n} update{'s' if n != 1 else ''} waiting: {', '.join(updates)}",
                "action": "update", "estimate": ctx.get("estimate")}
    if ctx.get("apps_changed") or ctx.get("components_moved"):
        return {"line": "Apps changed — put them on the board",
                "action": "update", "estimate": ctx.get("estimate")}
    # Offline outranks the tool checks: with no network `gh auth status` fails
    # too, and "gh is not signed in" is the wrong thing to tell someone whose
    # wifi is off.
    if ctx.get("offline"):
        return {"line": "No connection — can't check for updates",
                "action": "wrong", "estimate": None}
    missing = ctx.get("tools_missing") or []
    if missing:
        return {"line": f"Set up: {missing[0]}", "action": "wrong", "estimate": None}
    return {"line": "Everything is up to date", "action": "none", "estimate": None}


ESP_IDF_BUILD_DEPTH = 150    # characters a build path adds below the project dir
WINDOWS_MAX_PATH = 260
FREE_DISK_WARN_GB = 5        # two board revisions' build dirs, with room to spare


def path_problems(project_dir: str, platform: str, is_windows: bool,
                  longpaths: bool | None) -> list[str]:
    """What about where the project lives will break a build — before it does."""
    out = []
    if platform == "esp-idf" and " " in project_dir:
        out.append("the project folder has a space in its path — ESP-IDF can't build there")
    if platform == "esp-idf" and not project_dir.isascii():
        out.append("the project folder's path has non-English letters — ESP-IDF tools "
                   "choke on them")
    if is_windows and not longpaths and \
            len(project_dir) + ESP_IDF_BUILD_DEPTH > WINDOWS_MAX_PATH:
        out.append(f"the path is {len(project_dir)} characters and Windows long paths "
                   f"are off — builds go ~{ESP_IDF_BUILD_DEPTH} deeper than the "
                   f"{WINDOWS_MAX_PATH} limit allows")
    return out


def wrong_rows(f: dict) -> list[dict]:
    rows = []
    dev, b = f.get("device"), f.get("board") or {}
    if f.get("platform") == "pc":
        built = f.get("sim_built")
        rows.append({"ok": bool(built), "title": "Simulator",
                     "detail": f"built {built}" if built else
                               "not built yet — [1] Update my CrossPad builds it",
                     "fix": None, "action": None})
    elif dev:
        rows.append({"ok": True, "title": "Board found",
                     "detail": f"{dev.get('board_rev') or b.get('rev') or '?'}, firmware "
                               f"{dev.get('fw_rev') or '?'}", "fix": None, "action": None})
        if b.get("mismatch"):
            rows.append({"ok": False, "title": "Firmware",
                         "detail": f"{b.get('fw_rev')} firmware on a {b.get('rev')} board",
                         "fix": "[Enter] Update my CrossPad", "action": "update"})
        else:
            rows.append({"ok": True, "title": "Firmware", "detail": "matches the board",
                         "fix": None, "action": None})
    else:
        rows.append({"ok": False, "title": "Board found",
                     "detail": "No CrossPad found — plug it in over USB. Plugged in? "
                               "On the pad: hold the encoder → Settings → USB → CDC",
                     "fix": None, "action": None})
    tools_bad = []
    if f.get("idf_path") == "":
        tools_bad.append("ESP-IDF not found — run the CrossPad installer again "
                         "(see README), or open a terminal that has idf.py")
    if f.get("git_ok") is False:
        tools_bad.append("git is not installed — get it from git-scm.com")
    good = ([] if f.get("idf_path") in ("-", None) else ["ESP-IDF ok"]) + \
        (["git ok"] if f.get("git_ok") else []) + [f"Python {f.get('python')}"]
    rows.append({"ok": not tools_bad, "title": "Tools",
                 "detail": ", ".join(good) if not tools_bad else "; ".join(tools_bad),
                 "fix": "; ".join(tools_bad) or None, "action": None})
    if f.get("cert_problem"):
        rows.append({"ok": False, "title": "HTTPS certificates",
                     "detail": "Python can't verify GitHub's certificate",
                     "fix": "macOS: open your Python folder in Applications and run "
                            "'Install Certificates.command'", "action": None})
    probs = f.get("path_problems") or []
    if probs:
        rows.append({"ok": False, "title": "Project folder", "detail": "; ".join(probs),
                     "fix": "move the project to a short plain folder, e.g. C:\\cp or ~/cp",
                     "action": None})
    free = f.get("free_gb")
    if free is not None and free < FREE_DISK_WARN_GB:
        rows.append({"ok": False, "title": "Disk space",
                     "detail": f"{free:.1f} GB free — a build needs about {FREE_DISK_WARN_GB} GB",
                     "fix": "free some space", "action": None})
    if f.get("defender_hint"):
        rows.append({"ok": None, "title": "Windows Defender",
                     "detail": "scans every file a build writes — builds take about twice as long",
                     "fix": "PowerShell as admin: Add-MpPreference -ExclusionPath "
                            f"\"{f['defender_hint']}\"", "action": None})
    # Reading apps needs no account; only publishing your own does.
    rows.append({"ok": True if f.get("gh_ok") else None, "title": "GitHub sign-in",
                 "detail": (f"signed in as {f.get('gh_user')}" if f.get("gh_ok") else
                            "not signed in — only needed to publish your own apps"),
                 "fix": None if f.get("gh_ok") else "run: gh auth login (only for publishing)",
                 "action": None})
    if f.get("pyserial") is False:
        rows.append({"ok": False, "title": "USB serial",
                     "detail": "the Python package pyserial is missing — without it "
                               "nothing here can talk to the board",
                     "fix": "[Enter] install it", "action": "install_pyserial"})
    guard = f.get("usb_guard")
    if guard == "1":
        rows.append({"ok": False, "title": "USB serial guard",
                     "detail": "the board asks before switching USB mode",
                     "fix": "[Enter] turn it off on this board (bench use)", "action": "usb_guard_off"})
    elif guard == "0":
        rows.append({"ok": True, "title": "USB serial guard", "detail": "off", "fix": None, "action": None})
    if f.get("offline"):
        rows.append({"ok": False, "title": "Internet",
                     "detail": "no connection — updates and new apps need it",
                     "fix": "Connect, then [Enter] to look again", "action": "refresh"})
    else:
        # "ok" rather than "reachable": nothing here pings anything, it only
        # reports that nothing has failed to reach GitHub this session.
        rows.append({"ok": True, "title": "Internet", "detail": "ok",
                     "fix": None, "action": None})
    age = f.get("registry_age", -1)
    stale = age < 0 or age > AVAILABLE_MAX_AGE_SECONDS
    rows.append({"ok": None if stale else True, "title": "Registry",
                 "detail": "never fetched" if age < 0 else f"last fetched {age // 3600} h ago"
                 if age >= 3600 else f"fetched {age // 60} min ago",
                 "fix": "[Enter] refresh", "action": "refresh"})
    last = f.get("last_update")
    rows.append({"ok": (last or {}).get("ok") if last else None, "title": "Last update",
                 "detail": (f"{last['finished'][:16].replace('T', ' ')}, "
                            f"{'all versions matched' if last.get('ok') else 'failed'}") if last else "never",
                 "fix": "[l] open the log" if last else None, "action": "log" if last else None})
    if f.get("can_go_back"):
        rows.append({"ok": None, "title": "Go back",
                     "detail": f"the update before changed {f['can_go_back']}",
                     "fix": "[Enter] go back to the versions from before", "action": "go_back"})
    prev = f.get("previous_firmware")
    if prev:
        rows.append({"ok": None, "title": "Previous firmware",
                     "detail": "the board still has the one before in its second slot"
                               + (f" ({prev})" if prev != "-" else ""),
                     "fix": "[Enter] switch back to it — seconds, no build",
                     "action": "switch_slot"})
    if f.get("remembered_board") and dev and dev.get("board_rev") \
            and dev["board_rev"] != f["remembered_board"]:
        rows.append({"ok": False, "title": "Remembered board",
                     "detail": f"{f['remembered_board']} remembered, {dev['board_rev']} plugged in",
                     "fix": "[Enter] forget the remembered board", "action": "forget_board"})
    return rows


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
        # Everything network-shaped asks this first. One failed reach sets it
        # for the session: a machine that cannot reach GitHub will not reach it
        # five apps later either, and retrying once per app is what turned a
        # missing connection into an error beside every app on screen.
        self._offline = False
        self._registry_cache: dict | None = None
        # Python could not verify GitHub's certificate — a python.org install
        # on macOS without "Install Certificates.command" — not a missing network.
        self.cert_problem = False

    # -- offline ---------------------------------------------------------------

    @property
    def offline(self) -> bool:
        return self._offline

    def retry_network(self):
        """Forget that the network was unreachable, so the next call tries again."""
        self._offline = False
        self._registry_cache = None

    @staticmethod
    def looks_offline(text: str) -> bool:
        """Does this git/gh failure read as 'no network' rather than 'no such repo'?"""
        t = (text or "").lower()
        return any(s in t for s in (
            "could not resolve host", "unable to access", "network is unreachable",
            "connection refused", "connection timed out", "temporary failure in name",
            "no route to host", "operation timed out", "failed to connect"))

    # -- registry loading -----------------------------------------------------

    def _fetch_remote_registry(self) -> dict | None:
        if self._offline:
            return None
        data = None
        try:
            data = json.loads(http_get(raw_url(REMOTE_REGISTRY_REPO, REMOTE_REGISTRY_PATH,
                                               "main")))
        except NetError as e:
            self.cert_problem = self.cert_problem or e.cert
            data = self._gh_contents(REMOTE_REGISTRY_REPO, REMOTE_REGISTRY_PATH)
            if data is None:
                # Silent on purpose: the screens say "no connection" in one place.
                self._offline = e.offline or e.cert
                return None
        except ValueError:
            return None
        with open(self.local_registry_path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        return data

    @staticmethod
    def _gh_contents(owner_repo: str, path: str) -> dict | None:
        """The same file through `gh api` — a proxy gh is set up for, a private repo."""
        try:
            import base64
            r = subprocess.run(
                ["gh", "api", f"repos/{owner_repo}/contents/{path}", "--jq", ".content"],
                capture_output=True, text=True, check=True, timeout=15)
            return json.loads(base64.b64decode(r.stdout.strip()).decode())
        except (subprocess.CalledProcessError, FileNotFoundError,
                subprocess.TimeoutExpired, ValueError):
            return None

    def _is_cache_fresh(self) -> bool:
        if not self.local_registry_path.exists():
            return False
        age = datetime.now().timestamp() - self.local_registry_path.stat().st_mtime
        return age < CACHE_MAX_AGE_SECONDS

    def _load_registry(self) -> dict:
        """The app list, network at most once per session.

        app_status() calls this for every app, so an uncached miss used to mean
        one gh invocation per app — and, offline, one failure message per app.
        """
        if self._registry_cache is not None:
            return self._registry_cache

        if not self._is_cache_fresh():
            remote = self._fetch_remote_registry()
            if remote:
                self._registry_cache = remote
                return remote

        if self.local_registry_path.exists():
            with open(self.local_registry_path) as f:
                cached = json.load(f)
            self._registry_cache = cached
            return cached

        print("No connection, and no app list saved on this computer yet.")
        print("  Connect to the internet once and start this again.")
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
        owner_repo = owner_repo_of(info.get("repo", ""))
        if not owner_repo or self._offline:
            return []
        try:
            data = json.loads(http_get(raw_url(owner_repo, "crosspad-app.json"), timeout=10))
        except (NetError, ValueError):
            data = self._gh_contents(owner_repo, "crosspad-app.json") or {}
        return data.get("changelog", [])

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
        # 1b. Where the CrossPad installer put it
        p = self._load_local_config().get("idf_path", "")
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
            Path("C:/esp/esp-idf"),        # the installer's short path on Windows
        ]:
            if candidate.is_dir():
                return str(candidate)
        return ""

    def run_command(self, cmd: str) -> int:
        """Run a shell command in the project dir, return exit code."""
        cmd = self._wrap_idf(cmd)
        _alt_screen_off()
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
        _save_terminal()
        _alt_screen_on()
        return rc

    def _wrap_idf(self, cmd: str) -> str:
        if self.config.platform != "esp-idf":
            return cmd
        idf_path = self._find_idf_path()
        if not idf_path:
            return cmd
        if sys.platform == "win32":
            export = os.path.join(idf_path, "export.bat")
            return f'call "{export}" >nul 2>&1 && {cmd}' if os.path.exists(export) else cmd
        export = os.path.join(idf_path, "export.sh")
        if not os.path.exists(export):
            return cmd
        return (f"export IDF_PATH={idf_path} IDF_PATH_FORCE=1 && "
                f". {export} > /dev/null 2>&1 && {cmd}")

    CANCELLED = -2

    def run_streaming(self, cmd: str, on_line, log=None, cancel=None) -> int:
        """Run a shell command; hand every output line to on_line (and to log).

        Unlike run_command this never writes to the terminal — the caller
        owns the screen and decides what one line of ninja is worth showing.

        `cancel()` is asked between lines and every 0.2 s of silence; True, or
        Ctrl+C, stops the whole process tree and returns CANCELLED. Before
        this, Ctrl+C in a build unwound the entire TUI back to the shell and
        the screen's own "[q] cancel" did nothing while a step ran.
        """
        import queue
        import threading
        popen_kw = {}
        if sys.platform == "win32":
            popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kw["start_new_session"] = True   # the whole tree dies together
        proc = subprocess.Popen(
            self._wrap_idf(cmd), shell=True, cwd=str(self.project_dir),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", bufsize=1, **popen_kw)
        lines: "queue.Queue[str | None]" = queue.Queue()

        def pump():
            for raw in proc.stdout:
                lines.put(raw.rstrip("\r\n"))
            lines.put(None)

        threading.Thread(target=pump, daemon=True).start()
        try:
            while True:
                try:
                    line = lines.get(timeout=0.2)
                except queue.Empty:
                    line = ""
                    if cancel is not None and cancel():
                        raise KeyboardInterrupt
                    continue
                if line is None:
                    break
                if log is not None:
                    log.write(line + "\n")
                    log.flush()
                on_line(line)
                if cancel is not None and cancel():
                    raise KeyboardInterrupt
        except KeyboardInterrupt:
            _kill_tree(proc)
            if log is not None:
                log.write("\n(stopped)\n")
            return self.CANCELLED
        return proc.wait()

    def check_gh_auth(self) -> tuple[bool, str]:
        """Check if gh CLI is authenticated. Returns (ok, username)."""
        try:
            r = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True, text=True, check=False, timeout=5,
            )
            if r.returncode == 0:
                # "Logged in to github.com account matixan (keyring)" (gh ≥ 2.40)
                # or "Logged in to github.com as matixan" (older gh).
                m = _re.search(r"Logged in to \S+ (?:account|as) (\S+)", r.stdout + r.stderr)
                return True, m.group(1) if m else "authenticated"
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

    # -- what the shared components are, and what an app asks of them ---------

    VERSION_HEADERS = {
        "crosspad-core": ("include/crosspad/CrosspadCoreVersion.hpp", "CROSSPAD_CORE_VERSION"),
        "crosspad-gui": ("include/crosspad-gui/CrosspadGuiVersion.hpp", "CROSSPAD_GUI_VERSION"),
    }

    def component_versions(self) -> dict:
        out = {}
        for comp, (rel, prefix) in self.VERSION_HEADERS.items():
            path = self.component_path(comp)
            if not path:
                continue
            try:
                text = (self.project_dir / path / rel).read_text(errors="replace")
            except OSError:
                continue
            nums = [_re.search(rf"#define\s+{prefix}_{p}\s+(\d+)", text) for p in
                    ("MAJOR", "MINOR", "PATCH")]
            if all(nums):
                out[comp] = tuple(int(m.group(1)) for m in nums)
        return out

    def requires_at(self, app_id: str, ref: str) -> dict | None:
        """The requirements an app declares at a tag or commit (after a fetch)."""
        path = self.app_status(app_id)["path"]
        r = self._sub_git(path, "show", f"{ref}:crosspad-app.json")
        if r.returncode != 0:
            return None
        try:
            return json.loads(r.stdout).get("requires")
        except ValueError:
            return None

    # -- ready-built firmware ---------------------------------------------------

    def official_release(self, refresh: bool = False) -> dict | None:
        """The newest published release of this platform: tag + asset URLs.

        GitHub's anonymous API, cached for an hour. None when the platform
        publishes nothing, nothing is published yet, or there is no network.
        """
        repo = getattr(self.config, "release_repo", None) or RELEASE_REPOS.get(self.config.platform)
        if not repo:
            return None
        cache = self.project_dir / RELEASE_FILE
        if not refresh and cache.exists() and \
                time.time() - cache.stat().st_mtime < CACHE_MAX_AGE_SECONDS:
            try:
                return json.loads(cache.read_text()) or None
            except ValueError:
                pass
        if self._offline:
            return None
        try:
            data = json.loads(http_get(f"{API_BASE}/repos/{repo}/releases/latest"))
        except NetError as e:
            if e.offline:
                self._offline = True
                return None
            # 404: nothing published — or a private repo, which gh can still see.
            data = self._gh_json("api", f"repos/{repo}/releases/latest") or {}
            if data.get("tag_name"):
                data["_via_gh"] = repo
        except ValueError:
            data = {}
        rel = ({"tag": data["tag_name"], "repo": repo, "private": bool(data.get("_via_gh")),
                "assets": {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}}
               if data.get("tag_name") else {})
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rel))
        return rel or None

    def _release_asset(self, rel: dict, name: str, timeout: float = 120) -> bytes:
        """One release file: anonymous for public repos, `gh release download`
        for private ones (the platform repo is private until the OS opens)."""
        if not rel.get("private"):
            return http_get(rel["assets"][name], timeout=timeout)
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run(["gh", "release", "download", rel["tag"], "-R", rel["repo"],
                                "-p", name, "-D", d], capture_output=True, text=True,
                               check=False, timeout=timeout)
            f = Path(d) / name
            if r.returncode != 0 or not f.exists():
                raise NetError(f"gh release download {name} failed", offline=False)
            return f.read_bytes()

    def submodule_heads(self) -> dict:
        """{path: full commit} for every submodule checked out here."""
        out = {}
        for sub in self.get_all_submodules():
            r = self._sub_git(sub["path"], "rev-parse", "HEAD")
            if r.returncode == 0:
                out[sub["path"]] = r.stdout.strip()
        return out

    def release_match(self, rel: dict) -> tuple[bool, str]:
        """Can the release's image replace a build of this checkout?"""
        name = release_asset_names(rel["tag"], "")["components"]
        url = rel.get("assets", {}).get(name)
        if not url:
            return False, "the release does not list its components"
        try:
            components = json.loads(self._release_asset(rel, name, 30)).get("components", {})
        except (NetError, ValueError):
            return False, "couldn't read the release's component list"
        dirty = [p for p in components if (self.project_dir / p).exists()
                 and self.get_submodule_dirty(p)]
        return checkout_matches_release(components, self.submodule_heads(), dirty,
                                        self.feature_overrides())

    def download_release_image(self, rel: dict, rev: str, on_line=None) -> Path | None:
        """The release's app image for this board revision, checksum verified."""
        names = release_asset_names(rel["tag"], rev)
        assets = rel.get("assets", {})
        if names["image"] not in assets or names["sums"] not in assets:
            return None
        dest = self.project_dir / FIRMWARE_DIR / rel["tag"] / names["image"]
        try:
            sums = parse_sha256sums(self._release_asset(rel, names["sums"], 30).decode())
            want = sums.get(names["image"])
            if not want:
                return None
            if not (dest.exists() and _sha256(dest) == want):
                if on_line:
                    on_line(f"downloading {names['image']}")
                blob = self._release_asset(rel, names["image"])
                import hashlib
                if hashlib.sha256(blob).hexdigest() != want:
                    if on_line:
                        on_line("the download is damaged (checksum differs)")
                    return None
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(blob)
        except NetError as e:
            if on_line:
                on_line(f"download failed: {e}")
            return None
        return dest

    # -- the catalog ------------------------------------------------------------

    def _gh_json(self, *args) -> dict | list | None:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, check=False,
                           timeout=30)
        if r.returncode != 0:
            return None
        try:
            return json.loads(r.stdout) if r.stdout.strip() else {}
        except ValueError:
            return None

    def catalog_check(self, app_id: str) -> tuple[list[str], str | None, dict | None]:
        """(problems, owner/repo, crosspad-app.json) for submitting one app."""
        path = self.app_status(app_id)["path"]
        meta = None
        try:
            meta = json.loads((self.project_dir / path / "crosspad-app.json").read_text())
        except (OSError, ValueError):
            pass
        owner_repo = owner_repo_of(self.app_git_state(path).get("origin", ""))
        vis = None
        if owner_repo:
            info = self._gh_json("repo", "view", owner_repo, "--json", "visibility")
            vis = (info or {}).get("visibility")
        try:
            listed = [r["repo"] for r in json.loads(http_get(raw_url(
                REMOTE_REGISTRY_REPO, "external-apps.json", "main"))).get("repos", [])]
        except (NetError, ValueError, KeyError):
            listed = []
        listed += [owner_repo_of(i.get("repo", "")) or "" for i in
                   self._load_registry().get("apps", {}).values()]
        return catalog_problems(meta, vis, owner_repo, listed), owner_repo, meta

    def submit_to_catalog(self, app_id: str) -> tuple[bool, str]:
        """Open a pull request that adds the app to external-apps.json.

        Through gh: fork CrossPad/crosspad-apps (once), a branch in the fork
        with the one-line addition, and the PR. The registry job picks the
        app up after the merge. Returns (ok, PR URL or the reason).
        """
        problems, owner_repo, meta = self.catalog_check(app_id)
        if problems:
            return False, problems[0]
        me = (self._gh_json("api", "user") or {}).get("login")
        if not me:
            return False, "not signed in to GitHub — run gh auth login in a terminal"
        subprocess.run(["gh", "repo", "fork", REMOTE_REGISTRY_REPO, "--clone=false"],
                       capture_output=True, check=False, timeout=60)
        fork = f"{me}/{REMOTE_REGISTRY_REPO.split('/')[1]}"
        cur = self._gh_json("api", f"repos/{REMOTE_REGISTRY_REPO}/contents/external-apps.json")
        base = self._gh_json("api", f"repos/{REMOTE_REGISTRY_REPO}/git/ref/heads/main")
        if not cur or not base:
            return False, "couldn't read the catalog on GitHub"
        import base64
        data = json.loads(base64.b64decode(cur["content"]).decode())
        data.setdefault("repos", []).append({"repo": owner_repo})
        branch = f"add-{app_id}"
        self._gh_json("api", "-X", "POST", f"repos/{fork}/git/refs",
                      "-f", f"ref=refs/heads/{branch}", "-f", f"sha={base['object']['sha']}")
        in_fork = self._gh_json("api", f"repos/{fork}/contents/external-apps.json?ref={branch}")
        body = base64.b64encode((json.dumps(data, indent=2) + "\n").encode()).decode()
        put = self._gh_json("api", "-X", "PUT", f"repos/{fork}/contents/external-apps.json",
                            "-f", f"message=Add {meta.get('name', app_id)} to the catalog",
                            "-f", f"content={body}", "-f", f"branch={branch}",
                            "-f", f"sha={(in_fork or cur)['sha']}")
        if put is None:
            return False, "couldn't write the change to your fork"
        r = subprocess.run(["gh", "pr", "create", "-R", REMOTE_REGISTRY_REPO,
                            "--head", f"{me}:{branch}",
                            "--title", f"Add {meta.get('name', app_id)}",
                            "--body", f"{meta.get('description', '')}\n\n"
                                      f"https://github.com/{owner_repo}\n\n"
                                      f"Submitted from CP Tools {MANAGER_VERSION}."],
                           capture_output=True, text=True, check=False, timeout=60)
        if r.returncode != 0:
            return False, (r.stderr.strip().splitlines() or ["gh pr create failed"])[-1]
        return True, r.stdout.strip()

    # -- going back -------------------------------------------------------------

    def app_heads(self) -> dict:
        """Full commit of every installed app on disk: what a 'go back' returns to."""
        out = {}
        for app_id in self._load_manifest().get("installed", {}):
            path = self.app_status(app_id)["path"]
            r = self._sub_git(path, "rev-parse", "HEAD")
            if r.returncode == 0:
                out[app_id] = r.stdout.strip()
        return out

    def rollback_plan(self) -> dict:
        """{app_id: commit} to return to, from the last successful update."""
        last = self.last_update() or {}
        prev, now = last.get("previous") or {}, last.get("after") or {}
        return {a: sha for a, sha in prev.items() if now.get(a) and now[a] != sha}

    def roll_back(self) -> list[str]:
        """Check the previous commits out again and keep them there.

        Each app lands on 'stays on a version' at the commit it had — otherwise
        the next update would carry it straight forward again. The dashboard
        says so; picking 'Latest release' in [2] undoes it per app.
        """
        done = []
        for app_id, sha in self.rollback_plan().items():
            path = self.app_status(app_id)["path"]
            if self._sub_git(path, "checkout", "--quiet", sha).returncode == 0:
                self.set_app_policy(app_id, TRACK_PINNED, commit=sha)
                self._git("add", path, check=False)
                done.append(app_id)
        return done

    def fw_slots(self) -> list[dict] | None:
        """The board's two firmware slots (FW_SLOTS), or None when it cannot say."""
        ok, text = self._cdc_exchange("FW_SLOTS", "rollback=", 4.0)
        if not ok:
            return None
        slots = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("FWSLOT:") and "slot=" in line:
                slots.append(dict(t.split("=", 1) for t in line[7:].split() if "=" in t))
        return slots or None

    def previous_firmware(self) -> dict | None:
        """The slot the board is not running, if it holds a firmware that started."""
        for sl in self.fw_slots() or []:
            if sl.get("running") == "0" and sl.get("state") in ("installed", "confirmed"):
                return sl
        return None

    def switch_firmware(self) -> bool:
        reply = self.cdc_verb("FW_SWITCH", timeout=4.0) or ""
        return reply.startswith("OK")

    # -- repair -------------------------------------------------------------------

    def repair_app(self, app_id: str, fresh: bool = False) -> tuple[bool, str]:
        """Put a broken app folder back. Local work is backed up first, always.

        repair: re-check-out the commit this project records, fetching what is
        missing — the folder stays. fresh: delete the folder and its git data
        and clone again; for a repository git itself cannot read any more.
        """
        st = self.app_status(app_id)
        path = st["path"]
        if st["git"]["exists"] and (self.project_dir / path / ".git").exists():
            self.backup_app(app_id)
        if fresh:
            shutil.rmtree(self.project_dir / path, ignore_errors=True)
            shutil.rmtree(self.project_dir / ".git" / "modules" / path, ignore_errors=True)
        r = self._git("submodule", "update", "--init", "--force", "--", path,
                      check=False, capture=True)
        if r.returncode != 0:
            lines = (r.stderr or r.stdout or "").strip().splitlines()
            return False, lines[-1] if lines else "git could not restore it"
        return True, "downloaded again" if fresh else "repaired"

    # -- diagnosis --------------------------------------------------------------

    def windows_longpaths(self) -> bool | None:
        """Both switches a deep ESP-IDF tree needs on Windows: the OS and git's."""
        if sys.platform != "win32":
            return None
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SYSTEM\CurrentControlSet\Control\FileSystem") as k:
                os_on = winreg.QueryValueEx(k, "LongPathsEnabled")[0] == 1
        except OSError:
            os_on = False
        r = subprocess.run(["git", "config", "--get", "core.longpaths"],
                           capture_output=True, text=True, check=False)
        return os_on and r.stdout.strip().lower() == "true"

    def doctor_facts(self, device: dict | None = None, gh: tuple | None = None) -> dict:
        """Everything wrong_rows() reads. No terminal, so the CLI and MCP get it too."""
        gh_ok, gh_user = gh if gh is not None else self.check_gh_auth()
        dev = device if device is not None else self.device_probe()
        guard = self.cdc_verb("USB_GUARD", timeout=2.0) if dev else None
        if guard:
            guard = ("1" if guard.strip().endswith("1") else
                     "0" if guard.strip().endswith("0") else None)
        build = self.get_build_info() if self.config.platform == "pc" else {}
        try:
            free_gb = shutil.disk_usage(self.project_dir).free / 1e9
        except OSError:
            free_gb = None
        is_win = sys.platform == "win32"
        prev_fw = (self.previous_firmware()
                   if dev and self.config.platform == "esp-idf" else None)
        return {
            "platform": self.config.platform, "device": dev,
            "board": self.board_info(refresh=True) or {},
            "sim_built": (f"{build['age_seconds'] // 60} min ago"
                          if build.get("exists") else None),
            "idf_path": (self._find_idf_path() if self.config.platform == "esp-idf" else "-"),
            "git_ok": shutil.which("git") is not None,
            "gh_ok": gh_ok, "gh_user": gh_user,
            "python": ".".join(map(str, sys.version_info[:3])),
            "pyserial": _has_module("serial"),
            "cert_problem": self.cert_problem, "offline": self._offline,
            "usb_guard": guard, "registry_age": self.get_cache_age(),
            "last_update": self.last_update(),
            "remembered_board": self._load_local_config().get("board"),
            "path_problems": path_problems(str(self.project_dir.resolve()),
                                           self.config.platform, is_win,
                                           self.windows_longpaths()),
            "free_gb": free_gb,
            "defender_hint": str(self.project_dir.resolve()) if is_win else None,
            "can_go_back": ", ".join(self.app_display_name(a) for a in self.rollback_plan()),
            "previous_firmware": prev_fw.get("ver", "-") if prev_fw else None,
        }

    def support_bundle(self, facts: dict | None = None) -> Path:
        """One zip that answers a helper's first ten questions.

        What happened (the last update's log and timings), what is installed
        and what was asked for (apps.json, crosspad.config.json, submodule
        commits), and the doctor's findings. No environment variables and no
        tokens; the personal config is included with anything secret-looking
        blanked.
        """
        import platform as _pf
        import zipfile
        facts = facts if facts is not None else self.doctor_facts()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = self.project_dir / WORK_ROOT / "support"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"crosspad-support-{stamp}.zip"
        lines = [f"CP Tools {MANAGER_VERSION} on {self.config.platform}",
                 f"OS: {_pf.platform()}   Python {sys.version.split()[0]}",
                 f"Project: {self.project_dir.resolve()}",
                 f"Created: {datetime.now(timezone.utc).isoformat()}", ""]
        for r in wrong_rows(facts):
            mark = {True: "ok ", False: "BAD", None: "?  "}[r["ok"]]
            lines.append(f"[{mark}] {r['title']}: {r['detail']}"
                         + (f"   -> {r['fix']}" if r["fix"] and r["ok"] is not True else ""))
        sub = self._git("submodule", "status", check=False, capture=True)
        head = self._git("log", "-1", "--format=%h %d %s", check=False, capture=True)
        lines += ["", "Project HEAD: " + (head.stdout or "").strip(), "",
                  "Submodules:", (sub.stdout or "").rstrip()]
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("report.txt", "\n".join(lines) + "\n")
            z.writestr("doctor.json", json.dumps(facts, indent=2, default=str))
            for rel in (LAST_UPDATE_FILE, MANIFEST_FILE, CONFIG_FILE):
                f = self.project_dir / rel
                if f.exists():
                    z.write(f, rel)
            log = self.project_dir / LAST_UPDATE_LOG
            if log.exists():
                tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-3000:]
                z.writestr(LAST_UPDATE_LOG, "\n".join(tail) + "\n")
            local = self._load_local_config()
            if local:
                z.writestr(LOCAL_CONFIG_FILE, json.dumps(_redact(local), indent=2))
        return dest

    # -- board revision (ESP-IDF supplies a resolver; other platforms have none) --

    def board_info(self, refresh: bool = False) -> dict | None:
        resolve = getattr(self.config, "board_resolve", None)
        if resolve is None:
            return None
        if refresh or not hasattr(self, "_board_cache"):
            try:
                self._board_cache = resolve()
            except Exception as e:  # noqa: BLE001 - a broken resolver must not take the TUI down
                self._board_cache = {"rev": None, "source": f"error: {e}"}
        return self._board_cache

    def idf_args(self) -> str:
        b = self.board_info()
        if not b or not b.get("rev"):
            return ""
        return f"-B {b['build_dir']} -DSDKCONFIG={b['sdkconfig']} "

    def ota_command(self) -> str:
        b = self.board_info()
        if not b or not b.get("rev"):
            return "python3 tools/ota_flash.py"
        return f"python3 tools/ota_flash.py --board {b['rev']}"

    def get_build_info(self) -> dict:
        """Get firmware build status. Returns dict with binary info."""
        # Platform-specific binary paths
        if self.config.platform == "esp-idf":
            b = self.board_info()
            build_dir = b["build_dir"] if b and b.get("rev") else "build"
            candidates = [
                self.project_dir / build_dir / "CrossPad.bin",
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

    # -- CP Tools' own settings (personal: crosspad.local.json) ---------------

    SETTINGS_DEFAULTS = {"check_updates": True, "early_features": False}

    def settings(self) -> dict:
        return dict(self.SETTINGS_DEFAULTS, **(self._load_local_config().get("cp_tools") or {}))

    def set_setting(self, key: str, value):
        local = self._load_local_config()
        local.setdefault("cp_tools", {})[key] = value
        self.save_config(local, local=True)

    def set_early_features(self, on: bool) -> list[str]:
        """Early features on: apps following the latest release follow development
        instead; off: back. Versions you picked and your own copies stay put.
        Written to the personal config, so it is your choice, not the project's."""
        moved = []
        for app_id in self._load_manifest().get("installed", {}):
            rule, _ = follow_rule(self.app_policy(app_id))
            if on and rule == "release":
                path = self.app_status(app_id)["path"]
                self.set_app_policy(app_id, TRACK_BRANCH, ref=self._get_default_branch(path),
                                    local=True)
                moved.append(app_id)
            elif not on and rule == "development":
                self.set_app_policy(app_id, TRACK_REGISTRY, local=True)
                moved.append(app_id)
        self.set_setting("early_features", on)
        return moved

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
        track = TRACK_ALIASES.get(track, track)
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
                 "origin": ""}
        if not full.exists():
            return state
        if not (full / ".git").exists():
            state["broken"] = "no git data in the folder"
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
        else:
            state["broken"] = "git can't read this folder"
            return state

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

        # An origin outside the official org is not suspicious in itself — you
        # publishing your own app is the normal case. What matters is whether
        # the worktree points somewhere OTHER than the repo this project
        # recorded, because then an update would pull from a different project
        # than the manifest describes.
        expected = (info.get("repo", "") or
                    self._load_manifest().get("installed", {})
                        .get(app_id, {}).get("repo", ""))
        if expected and git["origin"] and not self._same_repo(expected,
                                                              git["origin"]):
            flags.append("origin-mismatch")

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

    # -- what is available upstream, cached -----------------------------------
    #
    # The dashboard must not run `git fetch` on every redraw. One pass at TUI
    # start (and on demand) records per app what origin has; screens read the
    # record. Same TTL as the registry cache.

    @property
    def available_path(self) -> Path:
        return self.project_dir / AVAILABLE_FILE

    def available_age(self) -> int:
        if not self.available_path.exists():
            return -1
        return int(time.time() - self.available_path.stat().st_mtime)

    def available(self, app_id: str) -> dict | None:
        try:
            return json.loads(self.available_path.read_text()).get(app_id)
        except (OSError, ValueError):
            return None

    def refresh_available(self, app_ids: list[str], progress=None) -> dict:
        records = {}
        try:
            records = json.loads(self.available_path.read_text())
        except (OSError, ValueError):
            pass
        for app_id in app_ids:
            path = self.app_status(app_id)["path"]
            if not (self.project_dir / path / ".git").exists():
                continue
            if progress:
                progress(app_id)
            r = self._sub_git(path, "fetch", "--tags", "--quiet", "origin", timeout=60)
            if r.returncode != 0:
                # A machine with no network fails the same way for every app,
                # each time after its own DNS timeout. Stop at the first one and
                # keep whatever the cache already knew.
                if self.looks_offline(r.stderr):
                    self._offline = True
                    break
                records[app_id] = dict(records.get(app_id, {}), error="fetch failed")
                continue
            default = self._get_default_branch(path)
            tags = parse_tag_lines(self._sub_git(
                path, "for-each-ref", "--sort=-v:refname",
                "--format=%(refname:short) %(creatordate:short)", "refs/tags").stdout)
            newest = newest_release(tags)
            rec = {"tags": [list(t) for t in tags], "default_branch": default,
                   "dev_head": self._sub_git(path, "rev-parse", "--short",
                                             f"origin/{default}").stdout.strip(),
                   "dev_behind": self._count(path, f"HEAD..origin/{default}"),
                   "release_behind": self._count(path, f"HEAD..{newest}") if newest else 0,
                   "installed_tag": None,
                   "fetched_at": datetime.now(timezone.utc).isoformat()}
            exact = self._sub_git(path, "describe", "--tags", "--exact-match", "HEAD")
            if exact.returncode == 0:
                rec["installed_tag"] = exact.stdout.strip()
            # What an update would bring, in the authors' own words.
            rec["release_log"] = self._subjects(path, f"HEAD..{newest}") if newest else []
            rec["dev_log"] = self._subjects(path, f"HEAD..origin/{default}")
            records[app_id] = rec
        self.available_path.parent.mkdir(parents=True, exist_ok=True)
        # Written whole and renamed into place: the dashboard reads this file
        # while a background check is still writing it.
        tmp = self.available_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(records, indent=2))
        os.replace(tmp, self.available_path)
        return records

    def _subjects(self, path: str, range_spec: str, limit: int = 20) -> list[str]:
        r = self._sub_git(path, "log", "--no-merges", f"-{limit}", "--format=%s", range_spec)
        return [l for l in r.stdout.splitlines() if l.strip()] if r.returncode == 0 else []

    def _count(self, path: str, range_spec: str) -> int:
        r = self._sub_git(path, "rev-list", "--count", range_spec)
        return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else 0

    def set_version(self, app_id: str, row: VersionRow) -> tuple[bool, str]:
        """Apply a row from version_rows(): write the policy, check out a concrete pick."""
        self.ensure_config(quiet=True)
        if row.kind == "release":
            self.set_app_policy(app_id, TRACK_REGISTRY)
            return True, "follows the latest release"
        if row.kind == "development":
            self.set_app_policy(app_id, TRACK_BRANCH, ref=row.target)
            return True, f"follows {row.target}"
        path = self.app_status(app_id)["path"]
        r = self._sub_git(path, "checkout", "--quiet", row.target)
        if r.returncode != 0:
            return False, f"{row.target} is not a version this app has"
        sha = self._get_submodule_commit(path)
        self.set_app_policy(app_id, TRACK_PINNED, commit=sha)
        self._git("add", path, check=False)
        manifest = self._load_manifest()
        inst = manifest.get("installed", {}).get(app_id)
        if inst is not None:
            inst["version"] = sha
            inst["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_manifest(manifest)
        return True, f"stays on {row.label}"

    # -- the last update run ---------------------------------------------------

    def last_update(self) -> dict | None:
        try:
            return json.loads((self.project_dir / LAST_UPDATE_FILE).read_text())
        except (OSError, ValueError):
            return None

    def save_last_update(self, record: dict):
        p = self.project_dir / LAST_UPDATE_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(record, indent=2))

    def infra_submodules(self) -> list[str]:
        return [s["path"] for s in self.get_all_submodules() if s["infra"]]

    def app_display_name(self, app_id: str) -> str:
        """Human name for an app, registry or not.

        An app you generated yourself is not in the registry, but it still
        carries a crosspad-app.json — reading it keeps the UI from falling back
        to a bare id for exactly the apps a user cares most about.
        """
        info = self._load_registry().get("apps", {}).get(app_id)
        if info and info.get("name"):
            return info["name"]
        path = self.component_path(f"{self.config.lib_prefix}{app_id}")
        if path:
            meta = self.project_dir / path / "crosspad-app.json"
            if meta.exists():
                try:
                    return json.loads(meta.read_text()).get("name", app_id)
                except (OSError, ValueError):
                    pass
        return app_id

    @staticmethod
    def _same_repo(a: str, b: str) -> bool:
        """Compare remotes across the ways git spells the same repository."""
        def norm(url: str) -> str:
            url = url.strip().lower()
            url = url.replace("git@github.com:", "https://github.com/")
            url = url.replace("ssh://git@github.com/", "https://github.com/")
            if url.endswith(".git"):
                url = url[:-4]
            return url.rstrip("/")
        return norm(a) == norm(b)

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
        if "origin-mismatch" in st.get("flags", []):
            bits.append("origin≠manifest")
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
        b = self.board_info()
        if source.get("file") == "sdkconfig" and b and b.get("rev"):
            path = self.project_dir / b["sdkconfig"]
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

    def _parse_appver_lines(self, text: str) -> list[dict]:
        entries = []
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("APPVER:") or line.startswith("APPVER: end"):
                continue
            parts = line[len("APPVER:"):].strip().split()
            entry = {"component": parts[0] if parts else "?"}
            for token in parts[1:]:
                if "=" in token:
                    k, v = token.split("=", 1)
                    entry[k] = v
            entries.append(entry)
        return entries

    def _query_binary_versions(self, timeout: float) -> dict:
        """PC build: the simulator answers the same question via --versions."""
        out = {"ok": False, "error": "", "entries": [], "port": None}
        build = self.get_build_info()
        if not build.get("exists"):
            out["error"] = "simulator not built yet"
            return out
        binary = build["path"]
        out["port"] = binary
        try:
            r = subprocess.run([binary, "--versions"], capture_output=True,
                               text=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            out["error"] = f"{type(e).__name__}: {e}"
            return out
        out["entries"] = self._parse_appver_lines(r.stdout)
        if not out["entries"]:
            out["error"] = ("no APPVER output — simulator predates the "
                            "--versions flag")
            return out
        out["ok"] = True
        return out

    def component_path(self, component: str) -> str | None:
        """Locate a component on disk. Apps and shared submodules do not share
        a directory on every platform — PC keeps apps in src/apps and core/gui
        in lib — so the reported component name is resolved, not assumed."""
        for base in (self.config.lib_dir, "lib", "components", "."):
            candidate = self.project_dir / base / component
            if candidate.exists():
                return f"{base}/{component}" if base != "." else component
        return None

    def _cdc_exchange(self, verb: str, end_marker: str | None,
                      timeout: float) -> tuple[bool, str]:
        """Send one CDC line, collect the reply. (ok, text-or-reason)."""
        try:
            import serial
        except ImportError:
            return False, "pyserial not installed (pip install pyserial)"
        port = self.device_port()
        if not port:
            return False, ("no CrossPad CDC port — device unplugged, or in "
                           "USB audio mode (no CDC there)")
        try:
            with serial.Serial(port, 115200, timeout=0.5) as ser:
                ser.reset_input_buffer()
                ser.write(f"{verb}\r\n".encode())
                deadline = time.time() + timeout
                buf = ""
                while time.time() < deadline:
                    chunk = ser.read(512).decode("utf-8", "replace")
                    if chunk:
                        buf += chunk
                        if end_marker and end_marker in buf:
                            break
                        if not end_marker and "\n" in buf:
                            break
        except Exception as e:                      # noqa: BLE001 - report it
            return False, f"{type(e).__name__}: {e}"
        if not buf.strip():
            return False, "no reply — the board did not answer"
        return True, buf

    def cdc_verb(self, verb: str, timeout: float = 4.0) -> str | None:
        ok, text = self._cdc_exchange(verb, None, timeout)
        return text.strip().splitlines()[0] if ok else None

    chosen_device: str | None = None   # a device id picked when several are plugged in

    def devices(self) -> list[dict]:
        """Every CrossPad the platform can see (ESP-IDF: crosspad-hil devices)."""
        return list((self.board_info() or {}).get("devices") or [])

    def device_probe(self) -> dict | None:
        """What is plugged in, through the platform's probe when it has one.

        The board resolver's own scan (`board_info()`, e.g. `crosspad-hil
        devices` on ESP-IDF) already carries a "devices" list built from the
        same platform scan the device_probe hook would run — reuse its first
        entry instead of a second subprocess scan. Falls back to the hook
        when there is no cached board decision or it found nothing (no
        board_resolve hook, or a board that answered with an unknown
        revision).
        """
        devices = self.devices()
        if devices:
            chosen = [d for d in devices if d.get("id") == self.chosen_device]
            return chosen[0] if chosen else devices[0]
        probe = getattr(self.config, "device_probe", None)
        if probe is not None:
            try:
                return probe()
            except Exception:                       # noqa: BLE001 - a broken probe is "nothing found"
                return None
        port = self.device_port()
        return {"ports": {"cdc": {"path": port}}} if port else None

    def query_device_versions(self, timeout: float = 3.0) -> dict:
        """Ask a connected device what it was built from.

        Returns {"ok": bool, "error": str, "entries": [ {...} ]}. Never raises:
        a missing pyserial, a device in USB-audio mode (no CDC) and an older
        firmware without the command are all normal states to report, not
        failures to crash on.
        """
        if self.config.platform == "pc":
            return self._query_binary_versions(timeout)

        out = {"ok": False, "error": "", "entries": [], "port": None}
        ok, buf = self._cdc_exchange("APP_VERSIONS", "APPVER: end", timeout)
        if not ok:
            out["error"] = buf
            return out
        out["port"] = self.device_port()
        out["entries"] = self._parse_appver_lines(buf)

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
            path = self.component_path(component)
            local = self.app_git_state(path) if path else {
                "exists": False, "head": None}
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
                "local_present": local.get("exists", False),
                "match": match,
            })
        report["rows"] = rows
        report["stale"] = [r for r in rows if not r["match"]]
        return report

    # -- new app from template ------------------------------------------------
    #
    # Everything a CrossPad app needs is four files and a registration macro, so
    # the barrier to a new one should be a prompt, not an afternoon of copying
    # someone else's app and deleting the parts you did not want.

    TEMPLATE_REPO_PATH = "template"

    def _template_dir(self) -> Path | None:
        """Template source: the checked-out registry repo, or a cached copy.

        Platform wrappers only cache the manager itself, so a project that never
        cloned crosspad-apps fetches the template on demand and keeps it under
        .crosspad/, next to the other generated working data.
        """
        local = Path(__file__).resolve().parent / self.TEMPLATE_REPO_PATH
        if (local / "src").is_dir():
            return local

        cache = self.project_dir / WORK_ROOT / "template"
        if (cache / "src").is_dir():
            age = time.time() - cache.stat().st_mtime
            if age < CACHE_MAX_AGE_SECONDS:
                return cache

        if self._download_template(cache):
            return cache
        return cache if (cache / "src").is_dir() else None

    def _download_template(self, dest: Path) -> bool:
        """Pull template/ out of the registry repo with the gh CLI."""
        def fetch_dir(remote_path: str, local_dir: Path) -> bool:
            r = subprocess.run(
                ["gh", "api",
                 f"repos/{REMOTE_REGISTRY_REPO}/contents/{remote_path}",
                 "--jq", ".[] | [.type, .name, .path] | @tsv"],
                capture_output=True, text=True, check=False, timeout=30)
            if r.returncode != 0:
                return False
            local_dir.mkdir(parents=True, exist_ok=True)
            for line in r.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) != 3:
                    continue
                kind, name, path = parts
                if kind == "dir":
                    if not fetch_dir(path, local_dir / name):
                        return False
                elif kind == "file":
                    f = subprocess.run(
                        ["gh", "api",
                         f"repos/{REMOTE_REGISTRY_REPO}/contents/{path}",
                         "--jq", ".content"],
                        capture_output=True, text=True, check=False, timeout=30)
                    if f.returncode != 0:
                        return False
                    import base64
                    (local_dir / name).write_bytes(
                        base64.b64decode(f.stdout.strip()))
            return True

        try:
            return fetch_dir(self.TEMPLATE_REPO_PATH, dest)
        except (OSError, subprocess.SubprocessError):
            return False

    @staticmethod
    def app_id_to_class(app_id: str) -> str:
        return "".join(part.capitalize() for part in app_id.split("-") if part)

    @staticmethod
    def valid_app_id(app_id: str) -> bool:
        import re
        return bool(re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", app_id or ""))

    def _render_template(self, dest: Path, subs: dict) -> int:
        src = self._template_dir()
        if not src:
            raise RuntimeError("app template unavailable (no crosspad-apps "
                               "checkout and gh could not fetch it)")

        def substitute(text: str) -> str:
            for key, value in subs.items():
                text = text.replace(key, value)
            return text

        skip_names = {"app-registry.json", "apps.json", "crosspad.config.json",
                      "crosspad.local.json", ".DS_Store"}
        written = 0
        for path in sorted(src.rglob("*")):
            if path.is_dir() or "/.git/" in str(path):
                continue
            # Never ship working data that happened to land in the template
            # directory — a generated app must contain only the template.
            if path.name in skip_names or ".crosspad" in path.parts:
                continue
            rel = substitute(str(path.relative_to(src)))
            if rel.endswith(".tmpl"):
                rel = rel[:-len(".tmpl")]
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            # Only text is templated; images and other binaries are copied
            # as-is (their names still get substituted, above).
            if path.suffix.lower() in (".png", ".jpg", ".bin"):
                target.write_bytes(path.read_bytes())
            else:
                try:
                    target.write_text(substitute(path.read_text()))
                except UnicodeDecodeError:
                    target.write_bytes(path.read_bytes())
            written += 1
        return written

    def new_app(self, app_id: str, name: str = "", description: str = "",
                category: str = "tools", visibility: str = None,
                owner: str = "", install: bool = True,
                progress=None) -> dict:
        """Scaffold an app, optionally publish it, optionally install it here.

        visibility: None keeps it local (a plain directory in this project),
        "private"/"public" creates the GitHub repo and installs it back as a
        submodule so the project references a real remote.
        """
        result = {"ok": False, "error": "", "path": None, "repo": None}

        def step(message: str):
            if progress:
                progress(message)
            else:
                print(f"  {message}")

        if not self.valid_app_id(app_id):
            result["error"] = (f"'{app_id}' is not a valid app id "
                               f"(lowercase, digits and dashes)")
            return result

        component = f"{self.config.lib_prefix}{app_id}"
        install_path = f"{self.config.lib_dir}/{component}"
        if (self.project_dir / install_path).exists():
            result["error"] = f"{install_path} already exists"
            return result

        cls = self.app_id_to_class(app_id)
        subs = {
            "__APP_ID__": app_id,
            "__APP_CLASS__": cls,
            "__APP_UPPER__": app_id.upper().replace("-", "_"),
            "__APP_NAME__": name or cls,
            "__APP_DESC__": description or f"{name or cls} — a CrossPad app",
            "__APP_CATEGORY__": category,
        }

        # Build in a staging dir: when a remote is created the app has to exist
        # as its own repository before `git submodule add` can point at it.
        staging = self.project_dir / WORK_ROOT / "new" / component
        if staging.exists():
            import shutil
            shutil.rmtree(staging)
        staging.mkdir(parents=True)

        try:
            files = self._render_template(staging, subs)
        except RuntimeError as e:
            result["error"] = str(e)
            return result

        for args in (["init", "-q"],
                     ["add", "-A"],
                     ["-c", "commit.gpgsign=false", "commit", "-q", "-m",
                      f"feat: {subs['__APP_NAME__']} from the CrossPad app template"]):
            r = subprocess.run(["git", "-C", str(staging), *args],
                               capture_output=True, text=True, check=False)
            if r.returncode != 0 and args[0] in ("init", "add"):
                result["error"] = f"git {args[0]} failed: {r.stderr.strip()}"
                return result

        step(f"{files} file(s) generated")
        step("git repository initialised")

        repo_url = ""
        if visibility in ("private", "public"):
            if not owner:
                who = subprocess.run(["gh", "api", "user", "--jq", ".login"],
                                     capture_output=True, text=True, check=False)
                owner = who.stdout.strip() if who.returncode == 0 else ""
            if not owner:
                result["error"] = "gh is not authenticated (gh auth login)"
                return result
            slug = f"{owner}/{component}"
            r = subprocess.run(
                ["gh", "repo", "create", slug, f"--{visibility}",
                 "--source", str(staging), "--remote", "origin", "--push",
                 "--description", subs["__APP_DESC__"]],
                capture_output=True, text=True, check=False, timeout=120)
            if r.returncode != 0:
                result["error"] = f"gh repo create failed: {r.stderr.strip()}"
                return result
            repo_url = f"https://github.com/{slug}.git"
            result["repo"] = repo_url
            step(f"pushed to {slug} ({visibility})")

        if not install:
            result["ok"] = True
            result["path"] = str(staging)
            return result

        manifest = self._load_manifest()
        if repo_url:
            # Real remote: install it the way every other app is installed, so
            # the project records a submodule rather than a pile of files.
            r = self._git("submodule", "add", repo_url, install_path,
                          check=False, capture=True)
            if r.returncode != 0:
                result["error"] = f"submodule add failed: {r.stderr.strip()}"
                return result
            track, ref = TRACK_BRANCH, self._get_default_branch(install_path)
            step(f"added as a submodule at {install_path}")
        else:
            import shutil
            shutil.move(str(staging), str(self.project_dir / install_path))
            track, ref = TRACK_LOCAL, "local"
            step(f"placed at {install_path} (no remote)")

        manifest.setdefault("installed", {})[app_id] = {
            "version": self._get_submodule_commit(install_path)
                       if repo_url else "in-tree",
            "ref": ref,
            "repo": repo_url,
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_manifest(manifest)
        self.ensure_config(quiet=True)
        self.set_app_policy(app_id, track, ref=ref if track == TRACK_BRANCH else None)

        result["ok"] = True
        result["path"] = install_path
        result["track"] = track
        return result

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

        if app_name not in apps and not origin:
            print(f"Error: Unknown app '{app_name}'.")
            print(f"Available: {', '.join(apps.keys())}")
            print(f"An app outside the registry installs with "
                  f"--origin <repo url>.")
            sys.exit(1)

        if app_name in apps:
            info = apps[app_name]
        else:
            # Not in the registry, but the caller named a repo: your own app,
            # a private one, a fork. The registry is a directory, not a gate.
            info = {
                "name": app_name,
                "description": f"{app_name} (not in the registry)",
                "repo": origin,
                "component_path": f"{self.config.lib_dir}/"
                                  f"{self.config.lib_prefix}{app_name}",
                "platforms": [],
            }
            print(f"'{app_name}' is not in the registry — installing from "
                  f"{origin}.")

        if info.get("built_in"):
            print(f"Error: '{app_name}' is a built-in app and cannot "
                  f"be installed or removed via the app manager.")
            return

        if app_name in manifest.get("installed", {}):
            print(f"App '{app_name}' is already installed.")
            return

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
                default = self._get_default_branch(install_path)
                print(f"  no {ref} tag yet — using {default}")
                ref = default
                self._sub_git(install_path, "checkout", "--quiet", f"origin/{ref}")

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

        import shutil
        full_path = self.project_dir / install_path
        is_submodule = bool(self._get_submodule_branch(install_path)) or \
            (self.project_dir / ".gitmodules").exists() and \
            install_path in (self.project_dir / ".gitmodules").read_text()

        if is_submodule:
            try:
                self._git("submodule", "deinit", "-f", install_path)
                self._git("rm", "-f", install_path)
            except subprocess.CalledProcessError:
                print("Warning: git submodule removal had issues, "
                      "cleaning up manually.")
            modules_path = self.project_dir / ".git" / "modules" / install_path
            if modules_path.exists():
                shutil.rmtree(modules_path)
        # An app generated locally is a plain directory, not a submodule: the
        # submodule commands fail on it and used to leave the files behind.
        if full_path.exists():
            shutil.rmtree(full_path, ignore_errors=True)

        del manifest["installed"][app_name]
        self._save_manifest(manifest)

        cfg = self._load_config_raw()
        if cfg.get("apps", {}).pop(app_name, None) is not None:
            self.save_config(cfg)

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

            r = self._sub_git(install_path, "fetch", "--tags", "origin")
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
                # Latest release = the newest semver tag on origin; an app
                # without tags follows its default branch instead.
                tags = parse_tag_lines(self._sub_git(
                    install_path, "for-each-ref", "--sort=-v:refname",
                    "--format=%(refname:short) %(creatordate:short)", "refs/tags").stdout)
                checkout_ref = _release_target(tags, self._get_default_branch(install_path))
                r = self._sub_git(install_path, "checkout", "--quiet", checkout_ref)
                if r.returncode != 0:
                    skipped.append((name, f"checkout {checkout_ref} failed"))
                    continue
                ref = checkout_ref

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
            a = self.idf_args()
            print(f"\n  Next: idf.py {a}fullclean && idf.py {a}build")
        elif self.config.platform == "arduino":
            print(f"\n  Next: pio run --target clean && pio run")
        elif self.config.platform == "pc":
            print(f"\n  Next: rm -rf build && cmake -B build -G Ninja && cmake --build build")
        else:
            print(f"\n  Next: rebuild your project")


# == Update pipeline ==========================================================
#
# One Enter: download → firmware components → build → flash → check. The plan
# and the error copy are pure; UpdatePipeline (below) runs the subprocesses.

STEP_NAMES = ("download", "components", "build", "flash", "check")
STEP_TITLES = {"download": "Download updates", "components": "Firmware components",
               "build": "Build", "flash": "Flash", "check": "Check"}
STEP_IDLE = {"download": "apps that follow a newer version",
             "components": "what the firmware is built from",
             "build": "compile the firmware for your board",
             "flash": "over USB, no cable dance needed",
             "check": "the board answers with the new versions"}

NINJA_PROGRESS_RE = _re.compile(r"^\[(\d+)/(\d+)\]")


@dataclass
class StepResult:
    name: str
    ok: bool | None = None
    detail: str = ""
    seconds: float = 0.0
    error: str = ""


def plan_update(last: dict | None, installed_ids: list[str], can_flash: bool) -> dict:
    steps = list(STEP_NAMES) if can_flash else list(STEP_NAMES[:3])
    fullclean = (last is None
                 or set(last.get("installed_set", [])) != set(installed_ids))
    estimate = None
    if last and last.get("ok"):
        secs = {s["name"]: s.get("seconds", 0) for s in last.get("steps", [])}
        if all(n in secs for n in steps):
            estimate = int(sum(secs[n] for n in steps))
    return {"fullclean": fullclean, "steps": steps, "estimate": estimate}


def parse_ninja_progress(line: str) -> tuple[int, int] | None:
    m = NINJA_PROGRESS_RE.match(line)
    return (int(m.group(1)), int(m.group(2))) if m else None


def build_failure_where(log_tail: list[str], app_dirs: dict[str, str]) -> str:
    for line in log_tail:
        if "error" not in line.lower():
            continue
        for name, path in app_dirs.items():
            if path.replace("\\", "/") in line.replace("\\", "/"):
                return name
    return "the firmware"


# Known ways a build or a flash fails, in the words of the person at the
# keyboard. First match wins; the pattern is searched in the last lines of
# output. Same idea as idf.py's hints.yml, for the failures seen here.
FAILURE_HINTS = (
    (r"No space left on device|not enough space on the disk",
     "The disk is full — free a few GB, then [r] retry"),
    (r"Filename too long|path too long|filename or extension is too long|MAX_PATH",
     "Windows path too long — move the project to a short folder like C:\\cp, "
     "then [r] retry"),
    (r"undefined reference to `?_register_\w+_app",
     "An app changed without a clean build — [r] retry starts clean"),
    (r"idf\.py: (command )?not found|'idf\.py' is not recognized",
     "ESP-IDF isn't set up in this terminal → [3] Something's wrong"),
    (r"No module named '?serial'?",
     "The Python package pyserial is missing → [3] Something's wrong installs it"),
    (r"Permission denied: '?/dev/tty",
     "No permission for the USB port — Linux: sudo usermod -aG dialout $USER, "
     "then log out and back in"),
    (r"could not open port|Access is denied|Resource busy|port is busy",
     "Another program holds the CrossPad's USB port — close serial monitors "
     "and DAWs, then [r] retry"),
    (r"fatal: not a git repository|does not appear to be a git repository",
     "A component folder is broken → [2], open the app, Repair"),
    (r"CMakeLists\.txt.*(No such file|does not exist)",
     "A component is missing its files → [r] retry downloads it again"),
)


def explain_failure(log_tail: list[str]) -> str | None:
    text = "\n".join(log_tail[-60:])
    for pattern, hint in FAILURE_HINTS:
        if _re.search(pattern, text, _re.IGNORECASE):
            return hint
    return None


def error_line(step: str, reason: str, subject: str = "") -> str:
    table = {
        ("download", "offline"): "Can't reach GitHub — check your connection, then [r] retry",
        ("download", "failed"): "Couldn't update {s} → [r] retry   [3] Something's wrong",
        ("components", "failed"): "Couldn't fetch firmware components → [r] retry",
        ("build", "no-tools"): "Build tools are missing → [3] Something's wrong",
        ("build", "no-board"): "Which board? Answer above, then [r] retry",
        ("build", "failed"): "Build failed in {s} → [c] show the error   [3] Something's wrong",
        ("flash", "no-answer"): "The board isn't answering → [r] retry   [3] Something's wrong",
        ("flash", "failed"): "Flash failed → [c] show the error   [r] retry",
        ("check", "mismatch"): "The board still runs the old {s} → [r] flash again",
        ("check", "no-answer"): "The board isn't answering after the flash → [r] retry   [3] Something's wrong",
        ("build", "stopped"): "Stopped → [r] build again",
        ("flash", "stopped"): "Flash stopped — if the board shows nothing, [r] flash again",
        ("any", "stopped"): "Stopped → [r] start this step again",
    }
    return table.get((step, reason), f"{STEP_TITLES.get(step, step)} failed → [r] retry").replace("{s}", subject)


class UpdatePipeline:
    """Download → components → build → flash → check, rendered through `ui`.

    Every step returns instead of raising; the failing step carries the line
    the screen shows. The full output of every subprocess goes to
    LAST_UPDATE_LOG; the timings to LAST_UPDATE_FILE for the next estimate.
    """

    def __init__(self, mgr, ui):
        self.mgr, self.ui = mgr, ui
        self.installed = list(mgr._load_manifest().get("installed", {}).keys())
        can_flash = getattr(mgr.config, "flash_ota", None) is not None
        self.plan = plan_update(mgr.last_update(), self.installed, can_flash)
        self.steps = [StepResult(n, detail=STEP_IDLE[n]) for n in self.plan["steps"]]
        self.tail = ""
        self.progress = None
        self.log = None
        self.log_tail: list[str] = []

    def step(self, name: str) -> StepResult:
        return next(s for s in self.steps if s.name == name)

    # -- driving ---------------------------------------------------------------

    def run(self) -> bool:
        return self.retry_from(self.steps[0].name)

    def retry_from(self, name: str) -> bool:
        started = datetime.now(timezone.utc)
        if name == self.steps[0].name:
            heads = getattr(self.mgr, "app_heads", None)
            self.before = heads() if heads else {}
        reset = getattr(self.ui, "reset_cancel", None)
        if reset is not None:
            reset()
        log_path = self.mgr.project_dir / LAST_UPDATE_LOG
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ok = True
        with open(log_path, "a" if name != self.steps[0].name else "w",
                  encoding="utf-8") as self.log:
            begun = False
            for s in self.steps:
                if s.name == name:
                    begun = True
                if not begun:
                    continue
                s.ok, s.error, s.detail = None, "", "…"
                self._render()
                t0 = time.time()
                self.log.write(f"\n== {STEP_TITLES[s.name]} ==\n")
                try:
                    ok = getattr(self, f"_{s.name}")(s)
                except KeyboardInterrupt:
                    s.error = error_line(s.name, "stopped") if s.name in ("build", "flash") \
                        else error_line("any", "stopped")
                    ok = False
                s.seconds = time.time() - t0
                s.ok = ok
                self._render()
                if not ok or self.ui.cancelled():
                    ok = False
                    break
        heads = getattr(self.mgr, "app_heads", None)
        prior = self.mgr.last_update() or {}
        record = {
            "started": started.isoformat(),
            "finished": datetime.now(timezone.utc).isoformat(),
            "ok": ok, "installed_set": self.installed,
            "build_rev": (self.mgr.board_info() or {}).get("rev"),
            "steps": [{"name": s.name, "ok": s.ok, "seconds": round(s.seconds, 1)}
                      for s in self.steps]}
        after = heads() if heads else {}
        before = getattr(self, "before", None) or {}
        if ok and before and before != after:
            # What the board ran before this update, for "go back".
            record["previous"], record["after"] = before, after
        else:
            record["previous"], record["after"] = prior.get("previous"), prior.get("after")
        self.mgr.save_last_update(record)
        return ok

    def _render(self):
        self.ui.render(self.steps, self.tail, self.progress)

    def _line(self, line: str):
        self.tail = line[-110:]
        self.log_tail = (self.log_tail + [line])[-40:]
        p = parse_ninja_progress(line)
        if p:
            self.progress = p
        self._render()

    # -- steps -----------------------------------------------------------------

    def _download(self, s: StepResult) -> bool:
        done, left = [], []
        for app_id in self.installed:
            st = self.mgr.app_status(app_id)
            name = self.mgr.app_display_name(app_id)
            rule, _ = follow_rule(st["policy"])
            if rule in ("own", "version"):
                continue
            force = False
            if st["blocking"]:
                choice = self.ui.ask_local_work(name)
                if choice != "backup":
                    left.append(name)
                    continue
                # update(force=True) backs up through guard() itself — no
                # need to also back up here (that took two identical
                # snapshots per confirmation).
                force = True
            self.tail = f"{name}: fetching"
            self._render()
            with _capture_stdout(self.log):
                self.mgr.update(app_name=app_id, force=force)
            after = self.mgr.app_status(app_id)["git"]["head"]
            if after != st["git"]["head"]:
                done.append(f"{name} {after}")
        bits = [", ".join(done) if done else "nothing new"]
        if left:
            bits.append(f"{', '.join(left)} — your changes, left alone")
        s.detail = "; ".join(bits)
        return True

    def _components(self, s: StepResult) -> bool:
        paths = self.mgr.infra_submodules()
        if not paths:
            s.detail = "none to update"
            return True
        r = self.mgr._git("submodule", "update", "--init", "--", *paths,
                          check=False, capture=True)
        self.log.write((r.stdout or "") + "\n")
        if r.returncode != 0:
            s.error = error_line("components", "failed")
            return False
        s.detail = ", ".join(os.path.basename(p) for p in paths)
        return True

    def _build(self, s: StepResult) -> bool:
        plat = self.mgr.config.platform
        # Before minutes of compiling, the two things that make it fail at the end.
        try:
            free_gb = shutil.disk_usage(self.mgr.project_dir).free / 1e9
        except OSError:
            free_gb = None
        if free_gb is not None and free_gb < 1:
            s.error = f"Only {free_gb:.1f} GB free — a build needs a few GB → [r] retry after freeing some"
            return False
        probs = path_problems(str(Path(self.mgr.project_dir).resolve()), plat,
                              sys.platform == "win32",
                              getattr(self.mgr, "windows_longpaths", lambda: None)())
        if probs:
            s.error = f"Can't build here: {probs[0]} → move the project to a short plain folder"
            return False
        if plat == "esp-idf":
            b = self.mgr.board_info(refresh=True)
            if b is not None and not b.get("rev"):
                rev = self.ui.ask_board(list(getattr(self.mgr.config, "board_revs", ())))
                if not rev:
                    s.error = error_line("build", "no-board")
                    return False
                try:
                    self.mgr.config.board_set(rev)
                    self.mgr.board_info(refresh=True)
                except Exception:
                    s.error = error_line("build", "no-board")
                    return False
            if self._use_release_image(s):
                return True
            a = self.mgr.idf_args()
            cmd = f"idf.py {a}fullclean && idf.py {a}build" if self.plan["fullclean"] \
                else f"idf.py {a}build"
        elif plat == "arduino":
            cmd = "pio run --target clean && pio run" if self.plan["fullclean"] else "pio run"
        else:
            cmd = ("cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug && cmake --build build"
                   if self.plan["fullclean"] else "cmake --build build")
        self.progress = None
        rc = self.mgr.run_streaming(cmd, self._line, self.log,
                                    cancel=getattr(self.ui, "poll_cancel", None))
        if rc == AppManager.CANCELLED:
            s.error = error_line("build", "stopped")
            return False
        if rc == 127:
            s.error = error_line("build", "no-tools")
            return False
        if rc != 0:
            hint = explain_failure(self.log_tail)
            if hint and "clean build" in hint:
                self.plan["fullclean"] = True
            dirs = {self.mgr.app_display_name(a): self.mgr.app_status(a)["path"]
                    for a in self.installed}
            s.error = hint or error_line("build", "failed",
                                         build_failure_where(self.log_tail, dirs))
            return False
        s.detail = "firmware ready"
        return True

    image: Path | None = None       # a downloaded release image standing in for a build

    def _use_release_image(self, s: StepResult) -> bool:
        """When this checkout is exactly a published release, download its
        image instead of compiling for minutes. Anything else builds."""
        ota = getattr(self.mgr.config, "flash_ota", None)
        rel_fn = getattr(self.mgr, "official_release", None)
        if ota is None or rel_fn is None or not _takes(ota, "image"):
            return False
        rel = rel_fn()
        if not rel:
            return False
        ok, why = self.mgr.release_match(rel)
        self.log.write(f"release {rel['tag']}: {'matches' if ok else why}\n")
        if not ok:
            return False
        rev = (self.mgr.board_info() or {}).get("rev")
        path = self.mgr.download_release_image(rel, rev, self._line) if rev else None
        if path is None:
            return False
        self.image = path
        s.detail = f"ready-built {rel['tag']} — no build needed"
        return True

    def _flash(self, s: StepResult) -> bool:
        devs = self.mgr.devices()
        if len(devs) > 1 and not self.mgr.chosen_device:
            pick = getattr(self.ui, "ask_device", None)
            self.mgr.chosen_device = pick(devs) if pick else None
            if not self.mgr.chosen_device:
                s.error = "Which CrossPad? Answer above, then [r] retry"
                return False
        dev = self.mgr.device_probe()
        if dev is None:
            self.tail = "Plug in your CrossPad — I'll flash it when I see it"
            self._render()
            if not self.ui.wait_for_board(self.mgr.device_probe):
                s.error = "Cancelled before the flash"
                return False
            dev = self.mgr.device_probe() or {}
        rev = (self.mgr.board_info() or {}).get("rev")
        ports = dev.get("ports") or {}
        has_cdc = bool((ports.get("cdc") or {}).get("path")) or dev.get("usb_mode") == "audio"
        if dev.get("usb_mode") == "audio":
            self.tail = ("The board is in USB audio mode — switching it to serial; "
                         "if it asks 'USB serial mode?', press Allow on the CrossPad")
            self._render()

        def on_line(line: str):
            self.log.write(line + "\n")
            self.log.flush()
            self._line(line)

        if has_cdc:
            ota = self.mgr.config.flash_ota
            kw = {}
            if _takes(ota, "device"):
                kw["device"] = dev.get("id")
            if self.image is not None:
                kw["image"] = str(self.image)
            rc = ota(rev, on_line, **kw)
        else:
            console = (ports.get("console") or {}).get("path")
            uart = getattr(self.mgr.config, "flash_uart", None)
            if not console or uart is None:
                s.error = error_line("flash", "no-answer")
                return False
            rc = uart(rev, console, on_line)
        if rc != 0:
            s.error = (explain_failure(self.log_tail)
                       or error_line("flash", "no-answer" if rc == 2 else "failed"))
            return False
        s.detail = "done, the board is restarting"
        return True

    def _check(self, s: StepResult) -> bool:
        deadline = time.time() + 30
        report = {"ok": False}
        while time.time() < deadline:
            report = self.mgr.device_diff()
            if report.get("ok"):
                break
            time.sleep(2)
        if not report.get("ok"):
            s.error = error_line("check", "no-answer")
            return False
        stale = report.get("stale", [])
        if stale:
            app = stale[0].get("app_id") or stale[0].get("component")
            s.error = error_line("check", "mismatch", self.mgr.app_display_name(app))
            return False
        s.detail = "every version on the board matches"
        return True


class _capture_stdout:
    """Route print() of the CLI-era manager methods into the update log."""
    def __init__(self, sink):
        self.sink = sink
    def __enter__(self):
        self._old = sys.stdout
        sys.stdout = self.sink if self.sink is not None else self._old
    def __exit__(self, *exc):
        sys.stdout = self._old


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
    track_cmd.add_argument("mode", choices=list(TRACK_ALIASES) + list(TRACK_MODES),
                           help="release | development | version | mine")
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

    new_cmd = sub.add_parser("new", help="Scaffold a new app from the template")
    new_cmd.add_argument("app_id", help="App id (lowercase-with-dashes)")
    new_cmd.add_argument("--name", default="", help="Display name")
    new_cmd.add_argument("--description", default="", help="One-line description")
    new_cmd.add_argument("--category", default="tools",
                         help="music | audio | tools | other")
    new_cmd.add_argument("--private", action="store_true",
                         help="Create a private GitHub repo and push")
    new_cmd.add_argument("--public", action="store_true",
                         help="Create a public GitHub repo and push")
    new_cmd.add_argument("--owner", default="",
                         help="GitHub owner (default: the gh account)")
    new_cmd.add_argument("--no-install", action="store_true",
                         help="Only generate; do not add it to this project")

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
    tui_cmd = sub.add_parser("tui", help="Interactive terminal UI")
    tui_cmd.add_argument("--plain", action="store_true",
                         help="No colour, no full-screen redraw (screen readers)")
    doctor_cmd = sub.add_parser("doctor", help="Check tools, board, network and "
                                               "project folder; say how to fix each")
    sub.add_parser("support", help="Save a zip with logs and findings for support")
    for p_ in (list_cmd, status_cmd, doctor_cmd, sub.choices["device"]):
        p_.add_argument("--json", action="store_true",
                        help="Machine-readable output (schema_version 1)")

    args = parser.parse_args()
    mgr = AppManager(os.getcwd(), config)

    if getattr(args, "json", False):
        sys.exit(_json_cli(mgr, args))
    if args.command == "doctor":
        mgr._load_registry()          # a stale list is refreshed, and a dead network shows
        rows = wrong_rows(mgr.doctor_facts())
        for r in rows:
            mark = {True: "OK ", False: "BAD", None: " ? "}[r["ok"]]
            print(f"  [{mark}] {r['title']:<20} {r['detail']}")
            if r["fix"] and r["ok"] is not True:
                print(f"        {'':<20} -> {r['fix']}")
        bad = [r for r in rows if r["ok"] is False]
        print(f"\n  {'Ready.' if not bad else f'{len(bad)} thing(s) to fix.'}\n")
        sys.exit(1 if bad else 0)
    if args.command == "support":
        print(f"Saved {mgr.support_bundle()}")
        print("Send it on the CrossPad Discord (#support) with a line about what you were doing.")
        return
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
        print(f"{args.app}: {args.mode}"
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
    elif args.command == "new":
        visibility = ("private" if args.private else
                      "public" if args.public else None)
        res = mgr.new_app(args.app_id, name=args.name,
                          description=args.description,
                          category=args.category, visibility=visibility,
                          owner=args.owner, install=not args.no_install)
        if not res["ok"]:
            print(f"Error: {res['error']}")
            sys.exit(1)
        print(f"\n  {args.app_id} ready at {res['path']}")
        if res.get("repo"):
            print(f"  repo: {res['repo']}")
        if res.get("track") == TRACK_LOCAL:
            print(f"  tracked as local — the manager will not touch it, and it "
                  f"reports ref=in-tree in build telemetry")
        mgr._print_next_steps()
    elif args.command == "device":
        report = mgr.device_diff()
        if not report.get("ok"):
            print(f"Device: {report.get('error')}")
            sys.exit(1)
        origin = ("built binary" if config.platform == "pc" else "device")
        print(f"\n  From {origin}: {report['port']}\n")
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
        if getattr(args, "plain", False):
            os.environ["CROSSPAD_PLAIN"] = "1"
            _set_plain()
        if _is_interactive():
            tui_main(config)
        elif args.command is None:
            parser.print_help()
        else:
            print("Error: TUI requires an interactive terminal.")
            sys.exit(1)
    else:
        parser.print_help()


def _json_cli(mgr: "AppManager", args) -> int:
    """`--json`: the same answers for scripts, CI and agents. Exit 0 on success."""
    out: dict = {"schema_version": 1, "command": args.command}
    rc = 0
    if args.command == "doctor":
        mgr._load_registry()
        facts = mgr.doctor_facts()
        out["rows"] = wrong_rows(facts)
        out["facts"] = facts
        rc = 1 if any(r["ok"] is False for r in out["rows"]) else 0
    elif args.command == "status":
        names = [args.app] if args.app else list(mgr._load_manifest().get("installed", {}))
        out["apps"] = []
        for a in names:
            st = mgr.app_status(a)
            rule, target = follow_rule(st["policy"])
            out["apps"].append(dict(st, follows=rule, follows_target=target,
                                    row=app_row(st, mgr.available(a),
                                                a in mgr._load_registry().get("apps", {}))))
    elif args.command == "list":
        installed = mgr._load_manifest().get("installed", {})
        out["apps"] = [dict(info, id=a, installed=a in installed,
                            compatible=mgr._is_compatible(info))
                       for a, info in mgr._load_registry().get("apps", {}).items()
                       if args.all or mgr._is_compatible(info)]
    elif args.command == "device":
        out.update(mgr.device_diff())
        rc = 0 if out.get("ok") and not out.get("stale") else 1
    print(json.dumps(out, indent=2, default=str))
    return rc


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

def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _redact(obj):
    """Blank anything that looks like a secret before it leaves the machine."""
    if isinstance(obj, dict):
        return {k: ("***" if _re.search(r"token|secret|password|key", str(k), _re.I)
                    else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


def _kill_tree(proc: subprocess.Popen):
    """Stop a shell=True child and everything it started (ninja, compilers)."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, check=False)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()


def _takes(fn, param: str) -> bool:
    """Does a platform hook accept this keyword? Older wrappers predate it."""
    import inspect
    try:
        return param in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _has_module(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None


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


# no-color.org: set and non-empty turns colour off. CROSSPAD_PLAIN goes
# further for screen readers and logs: no colour, no full-screen redraw —
# every screen is printed below the last one, as a stream a reader can follow.
PLAIN = False


def _set_plain():
    global PLAIN
    PLAIN = bool(os.environ.get("CROSSPAD_PLAIN"))
    if PLAIN or os.environ.get("NO_COLOR"):
        for name in [n for n in vars(_C) if n.isupper()]:
            setattr(_C, name, "")
    if PLAIN and "G" in globals():
        G.update(G_ASCII)


_set_plain()


# -- glyphs ------------------------------------------------------------------
#
# Windows' classic console without a UTF-8 code page draws boxes for most of
# these; Windows Terminal (WT_SESSION) and every POSIX terminal are fine.

G_UNICODE = {"ok": "✓", "fail": "✗", "warn": "!", "next": "▸", "bar_on": "█",
             "bar_off": "░", "dot_on": "●", "dot_off": "○", "arrow": "→",
             "back": "←", "rule": "─", "hand": "✋"}
G_ASCII = {"ok": "OK", "fail": "X", "warn": "!", "next": ">", "bar_on": "#",
           "bar_off": "-", "dot_on": "*", "dot_off": "o", "arrow": "->",
           "back": "<-", "rule": "-", "hand": "!"}


def _console_utf8() -> bool:
    try:
        import ctypes
        return ctypes.windll.kernel32.GetConsoleOutputCP() == 65001
    except (AttributeError, OSError):
        return False


def _use_ascii() -> bool:
    if os.environ.get("CROSSPAD_PLAIN"):
        return True
    if sys.platform != "win32":
        return False
    if os.environ.get("WT_SESSION"):
        return False
    return not _console_utf8()


G = dict(G_ASCII if _use_ascii() else G_UNICODE)


def _enable_windows_vt():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(h, ctypes.byref(mode)):
            k32.SetConsoleMode(h, mode.value | 0x0004)   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except (AttributeError, OSError):
        pass


# Mouse: the wheel scrolls, a click on a "[key]" label presses that key.
# POSIX terminals only — the Windows console path reads keys through msvcrt,
# which does not see mouse reports. CROSSPAD_NO_MOUSE=1 keeps it off (then
# the terminal's own text selection works without holding Shift).
MOUSE = sys.platform != "win32" and not os.environ.get("CROSSPAD_NO_MOUSE")


def _alt_screen_on():
    _enable_windows_vt()
    if not PLAIN:
        _w("\033[?1049h\033[H")
        if MOUSE:
            _w("\033[?1000h\033[?1006h")


def _alt_screen_off():
    if not PLAIN:
        if MOUSE:
            _w("\033[?1006l\033[?1000l")
        _w("\033[?1049l")


def _viewport(cursor: int, total: int, height: int) -> tuple[int, int]:
    """Rows [start, end) of a list `total` long to draw in `height` rows."""
    height = max(height, 1)
    if total <= height:
        return 0, total
    start = min(max(cursor - height + 1, 0), total - height)
    if cursor < start:
        start = cursor
    return start, start + height


_ANSI_RE = _re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_LABEL_RE = _re.compile(r"\[([^\]\s]{1,8})\]")
_LABEL_KEYS = {"enter": "enter", "esc": "esc", "q/esc": "q", "space": " ",
               "backspace": "backspace", "arrows": ""}
_hotspots: list[tuple[int, int, int, str]] = []    # (row, first col, last col, key)
_cur = [1, 1]                                        # 1-based row, col of the next char


def _track(text: str):
    """Follow where text lands on screen and remember every [key] label."""
    plain = _ANSI_RE.sub("", text)
    pos = 0
    for line_i, chunk in enumerate(plain.split("\n")):
        if line_i:
            _cur[0] += 1
            _cur[1] = 1
        if "\r" in chunk:
            chunk = chunk.rsplit("\r", 1)[1]
            _cur[1] = 1
        for m in _LABEL_RE.finditer(chunk):
            label = m.group(1).lower()
            key = _LABEL_KEYS.get(label, label if len(label) == 1 else "")
            if key:
                _hotspots.append((_cur[0], _cur[1] + m.start(), _cur[1] + m.end() - 1, key))
        _cur[1] += len(chunk)
        pos += len(chunk) + 1


def _w(s: str):
    """Write to stdout without newline."""
    if MOUSE:
        _track(s)
    sys.stdout.write(s)
    sys.stdout.flush()


def _hotspot_key(col: int, row: int) -> str:
    for r, c0, c1, key in reversed(_hotspots):
        if r == row and c0 <= col <= c1:
            return key
    return ""


def _get_size() -> tuple[int, int]:
    """Return (columns, rows) of terminal."""
    try:
        import shutil as _sh
        return _sh.get_terminal_size((80, 24))
    except Exception:
        return (80, 24)


def _clear():
    _hotspots.clear()
    _cur[0], _cur[1] = 1, 1
    _w("\n" + "=" * 40 + "\n" if PLAIN else "\033[2J\033[H")
    if not PLAIN:
        _cur[0], _cur[1] = 1, 1


def _hide_cursor():
    if not PLAIN:
        _w("\033[?25l")


def _show_cursor():
    if not PLAIN:
        _w("\033[?25h")


# Terminal state management — raw mode breaks subprocess output
_saved_termios = None
_raw_mode = False


def _save_terminal():
    """Enter raw mode for the whole TUI session.

    Cbreak (not raw) is held for the whole session. Toggling termios between
    every keypress hands anything still in the input queue back to the line
    discipline, so typing faster than the redraw — or pasting — silently loses
    characters. Cbreak rather than raw because raw also turns off output
    post-processing, and every screen here ends its lines with a bare \n.
    """
    global _saved_termios, _raw_mode
    try:
        import termios
        import tty
        fd = sys.stdin.fileno()
        _saved_termios = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        _raw_mode = True
    except (ImportError, OSError):
        pass


def _restore_terminal():
    """Restore terminal to normal (cooked) mode for subprocess output."""
    global _raw_mode
    _raw_mode = False
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


def _decode_key(ch: str) -> str:
    """Turn one raw character (and any escape tail) into a key name."""
    if ch == "\x1b":
        # Escape starts both a bare Esc keypress and every arrow / navigation
        # sequence. Reading a fixed two more bytes blocked forever on a lone
        # Esc — which the menus advertise as "cancel" — so wait briefly for a
        # continuation instead and treat a silent terminal as the bare key.
        nxt = _read_within(0.05)
        if nxt is None:
            return "esc"
        # CSI ("\x1b[") and SS3 ("\x1bO", application cursor mode) both
        # prefix the cursor keys.
        if nxt not in ("[", "O"):
            return "esc"
        code = _read_within(0.05)
        if code is None:
            return "esc"
        if code == "<":
            # SGR mouse report: ESC [ < button ; col ; row (M press | m release)
            body = ""
            while True:
                c = _read_within(0.05)
                if c is None:
                    return ""
                if c in "Mm":
                    break
                body += c
            try:
                btn, col, row = (int(v) for v in body.split(";"))
            except ValueError:
                return ""
            if btn == 64:
                return "up"
            if btn == 65:
                return "down"
            if c == "M" and btn == 0:
                return _hotspot_key(col, row)
            return ""
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


_resized = False
_win_size: tuple | None = None

# `?` on any screen: the TUI registers a hook; the title and key hints of the
# screen on display are recorded as they are drawn, so the help can never
# drift from what the screen actually offers.
_help_hook = None
_help_suspended = False
_screen_title = ""
_screen_hints = ""


def _install_resize_handler():
    global _resized
    try:
        import signal
        def on_winch(_sig, _frm):
            global _resized
            _resized = True
        signal.signal(signal.SIGWINCH, on_winch)
    except (ImportError, AttributeError, ValueError):
        pass   # no SIGWINCH on Windows; the next key redraws


def _read_key(timeout: float | None = None) -> str:
    """One key, or "" after `timeout` seconds, or "resize" after SIGWINCH.

    `?` opens the help for the screen on display and reads as "resize", so
    whatever loop asked redraws itself afterwards.
    """
    key = _read_key_raw(timeout)
    if key == "?" and _help_hook is not None and not _help_suspended:
        _help_hook(_screen_title, _screen_hints)
        return "resize"
    return key


def _read_key_raw(timeout: float | None = None) -> str:
    global _resized
    if _raw_mode:
        deadline = None if timeout is None else time.time() + timeout
        while True:
            if _resized:
                _resized = False
                return "resize"
            wait = 0.5 if deadline is None else max(min(deadline - time.time(), 0.5), 0)
            ch = _read_within(wait)
            if ch is not None:
                return _decode_key(ch)
            if deadline is not None and time.time() >= deadline:
                return ""

    try:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            return _decode_key(_read_raw_char())
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except (ImportError, OSError):
        import msvcrt
        # No SIGWINCH on Windows: poll the size while waiting, so a resized
        # console redraws at once instead of on the next key.
        global _win_size
        deadline = None if timeout is None else time.time() + timeout
        while not msvcrt.kbhit():
            size = _get_size()
            if _win_size is not None and size != _win_size:
                _win_size = size
                return "resize"
            _win_size = size
            if deadline is not None and time.time() >= deadline:
                return ""
            time.sleep(0.05)
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


def _read_key_blocking() -> str:
    """Like _read_key(), but a stray "" (timeout) or "resize" isn't an answer.

    For the single-shot reads that decide something on the one key they get —
    "press any key" prompts, one-key confirmations — a bare SIGWINCH must not
    read as the answer: it would silently discard whatever the screen was
    about to do (or dismiss it) instead of just redrawing.
    """
    while True:
        key = _read_key()
        if key not in ("", "resize"):
            return key


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
    """Single-line text input. Returns None on cancel. `?` is just a character here."""
    global _help_suspended
    _help_suspended = True
    try:
        return _text_input_loop(prompt, default)
    finally:
        _help_suspended = False


def _text_input_loop(prompt: str, default: str) -> str | None:
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
    global _screen_title, _screen_hints
    cursor = 0
    while True:
        _clear()
        _screen_title, _screen_hints = title, "[Enter] select   [q] back"
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
           f"[enter] select  [q/esc] back  [?] help{_C.RST}\n")
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
    _read_key_blocking()


class _PipelineUI:
    """Draws UpdatePipeline's state; owns nothing but the screen."""

    def __init__(self, tui: "_TUI"):
        self.tui = tui
        self._cancel = False

    def render(self, steps, tail, progress):
        _clear()
        self.tui._header("Update my CrossPad", self.tui._header_right())
        _w("\n")
        w = _get_size()[0]
        for s in steps:
            if s.ok is True:
                mark, col = G["ok"], _C.BGREEN
            elif s.ok is False:
                mark, col = G["fail"], _C.BRED
            elif s.detail == "…":
                mark, col = G["next"], _C.BYELLOW
            else:
                mark, col = " ", _C.GRAY
            detail = s.error or s.detail
            if s.detail == "…" and s.name == "build" and progress:
                n, m = progress
                width = 20
                filled = int(width * n / max(m, 1))
                pct = int(100 * n / max(m, 1))
                detail = (f"{G['bar_on'] * filled}{G['bar_off'] * (width - filled)}  "
                          f"{pct:3d} %")
            elif s.detail == "…":
                detail = "working…"
            line = f" {col}{mark:<2}{_C.RST}{STEP_TITLES[s.name]:<22} "
            _w(line + (f"{_C.BRED}{detail}{_C.RST}" if s.error else
                       f"{_C.GRAY if s.ok is None else ''}{detail[:w - 28]}{_C.RST}") + "\n")
        _w(f"\n {_C.DIM}{tail[:w - 4]}{_C.RST}\n")
        global _screen_hints
        _screen_hints = "[q] stop the step that is running (Ctrl+C does the same)"
        _w(f"\n{' ' * max(w - 14, 0)}{_C.GRAY}[q] stop{_C.RST}\n")

    def ask_local_work(self, app_name: str) -> str:
        _w(f"\n {_C.BYELLOW}{app_name} has changes you made.{_C.RST}\n")
        _w(f"   {_C.BCYAN}[Enter]{_C.RST} Leave it alone (keep my changes)\n")
        _w(f"   {_C.BCYAN}[b]{_C.RST}     Back it up to {BACKUP_ROOT} and update anyway\n")
        while True:
            key = _read_key()
            if key == "b":
                return "backup"
            if key in ("enter", "esc", "q"):
                return "leave"

    def ask_board(self, revs: list[str]) -> str | None:
        _w(f"\n {_C.BYELLOW}Which CrossPad do you have?{_C.RST}\n")
        for i, r in enumerate(revs, 1):
            _w(f"   {_C.BCYAN}[{i}]{_C.RST} {r}\n")
        _w(f"   {_C.GRAY}Look at the sticker on the back cover.{_C.RST}\n")
        while True:
            key = _read_key()
            if key.isdigit() and 1 <= int(key) <= len(revs):
                return revs[int(key) - 1]
            if key in ("esc", "q"):
                return None

    def ask_device(self, devices: list[dict]) -> str | None:
        _w(f"\n {_C.BYELLOW}Two or more CrossPads are plugged in. Which one?{_C.RST}\n")
        for i, d in enumerate(devices, 1):
            _w(f"   {_C.BCYAN}[{i}]{_C.RST} {d.get('id', '?')}  "
               f"{_C.GRAY}{d.get('board_rev') or '?'} board, firmware {d.get('fw_rev') or '?'}"
               f"{_C.RST}\n")
        while True:
            key = _read_key()
            if key.isdigit() and 1 <= int(key) <= len(devices):
                return devices[int(key) - 1].get("id")
            if key in ("esc", "q"):
                return None

    def wait_for_board(self, probe) -> bool:
        while True:
            key = _read_key(timeout=2.0)
            if key in ("q", "esc", "ctrl-c"):
                self._cancel = True
                return False
            if probe() is not None:
                return True

    def cancelled(self) -> bool:
        return self._cancel

    def poll_cancel(self) -> bool:
        """Non-blocking: was [q] pressed while a step runs?"""
        if _read_key(timeout=0) in ("q", "esc"):
            self._cancel = True
        return self._cancel

    def reset_cancel(self):
        self._cancel = False


# -- Main TUI class -----------------------------------------------------------

class _TUI:
    """Interactive TUI for CrossPad App Manager."""

    def __init__(self, config: PlatformConfig):
        self.config = config
        self.mgr = AppManager(os.getcwd(), config)
        self._serial_port = ""
        self._toast = ""
        self._device = None
        self._env_cache: dict | None = None
        self._env_at = 0.0
        self._stale = False
        self._reload()
        self._startup_refresh()

    # How long the answers that cost a subprocess are worth reusing. `gh auth
    # status` and the device probe are ~0.4 s and ~0.2 s, and neither changes
    # between two keypresses; without this they ran on every screen return.
    ENV_TTL_SECONDS = 30

    def _env(self, force: bool = False) -> dict:
        """Board, device and toolchain — the facts that cost a subprocess."""
        fresh = (not force and self._env_cache is not None
                 and time.time() - self._env_at < self.ENV_TTL_SECONDS)
        if not fresh:
            gh_ok, gh_user = self.mgr.check_gh_auth()
            self._env_cache = {
                "board": self.mgr.board_info(refresh=True) or {},
                "device": self.mgr.device_probe(),
                "gh_ok": gh_ok, "gh_user": gh_user,
                "git_ok": shutil.which("git") is not None,
                "idf_path": (self.mgr._find_idf_path()
                             if self.config.platform == "esp-idf" else "-"),
            }
            self._env_at = time.time()
        return self._env_cache

    def _reload(self, force_env: bool = False):
        """(Re)load registry, manifest, per-app status and dashboard rows."""
        self._registry = self.mgr._load_registry()
        self._manifest = self.mgr._load_manifest()
        self._apps = self._registry.get("apps", {})
        self._installed = self._manifest.get("installed", {})
        env = self._env(force=force_env)
        self._statuses = {a: self.mgr.app_status(a) for a in self._installed}
        self._rows = {a: app_row(st, self.mgr.available(a), a in self._apps)
                      for a, st in self._statuses.items()}
        self._device = env["device"]
        self._next = whats_next(self._dashboard_ctx())

    def _startup_refresh(self):
        """One fetch per app when the cache is older than an hour — in the
        background, so the first screen is there at once and fills in."""
        import threading
        age = self.mgr.available_age()
        if (0 <= age < AVAILABLE_MAX_AGE_SECONDS or not self._installed
                or not self.mgr.settings()["check_updates"]):
            return

        def work():
            try:
                self.mgr.refresh_available(list(self._installed))
            finally:
                self._stale = True

        self._bg = threading.Thread(target=work, daemon=True)
        self._bg.start()

    def _wait_background(self):
        """git must not fetch into a repo the update is about to move."""
        bg = getattr(self, "_bg", None)
        if bg is not None and bg.is_alive():
            _clear()
            _w(f"\n  {_C.GRAY}Finishing the update check…{_C.RST}\n")
            bg.join()

    @property
    def _checking(self) -> bool:
        bg = getattr(self, "_bg", None)
        return bg is not None and bg.is_alive()

    def _dashboard_ctx(self) -> dict:
        env = self._env()
        b = env["board"]
        last = self.mgr.last_update()
        updates = [self.mgr.app_display_name(a) for a, r in self._rows.items()
                   if r["state"] == "update"]
        apps_changed = bool(last) and set(last.get("installed_set", [])) != set(self._installed)
        moved = any(s["modified"] for s in self.mgr.get_all_submodules() if s["infra"])
        missing = []
        if self.config.platform == "esp-idf" and not env["idf_path"]:
            missing.append("ESP-IDF is not installed")
        if not env["git_ok"]:
            missing.append("git is not installed")
        if self.mgr.cert_problem:
            missing.append("Python can't verify GitHub's certificate")
        can_flash = getattr(self.config, "flash_ota", None) is not None
        failed = next((st["name"] for st in (last or {}).get("steps", [])
                       if st.get("ok") is False), None) if last and not last.get("ok") else None
        return {"unfinished": STEP_TITLES.get(failed) if failed else None,
                "board_rev": b.get("rev"), "fw_rev": b.get("fw_rev"),
                "mismatch": bool(b.get("mismatch")), "updates": updates,
                "apps_changed": apps_changed, "components_moved": moved,
                "tools_missing": missing, "offline": self.mgr.offline,
                "estimate": plan_update(last, list(self._installed), can_flash)["estimate"]}

    def _header_right(self) -> str:
        b = self._env()["board"]
        bits = []
        if b.get("rev"):
            bits.append(f"{b['rev']} board")
        if b.get("fw_rev"):
            bits.append(f"fw {b['fw_rev']} {G['ok'] if not b.get('mismatch') else G['fail']}")
        bits.append("connected" if self._device else "no board plugged in")
        if self._checking:
            bits.append("checking for updates…")
        return " · ".join(bits)

    @staticmethod
    def _fmt_estimate(seconds) -> str:
        if not seconds:
            return ""
        return f"  (~{max(round(seconds / 60), 1)} min)"

    @property
    def _cols(self):
        return _get_size()[0]

    def run(self):
        global _help_hook
        _help_hook = self._help
        _alt_screen_on()
        _save_terminal()
        _hide_cursor()
        _install_resize_handler()
        try:
            self._welcome()
            self._dashboard()
        except KeyboardInterrupt:
            pass
        finally:
            _restore_terminal()
            _clear()
            _alt_screen_off()

    def _welcome(self):
        """Once per project: what this is and the four things it does."""
        marker = self.mgr.project_dir / WORK_ROOT / "welcomed"
        if marker.exists():
            return
        _clear()
        self._header("Welcome to CP Tools", f"version {MANAGER_VERSION}")
        _w(f"""
  This keeps your CrossPad up to date and lets you choose its apps.
  Everything happens with a number key and Enter.

   {_C.BCYAN}[1]{_C.RST} Update my CrossPad   downloads what is new and puts it on the board
   {_C.BCYAN}[2]{_C.RST} Add or remove apps   and choose a version for each
   {_C.BCYAN}[3]{_C.RST} Something's wrong    every check, with what to do about it
   {_C.BCYAN}[4]{_C.RST} Developer tools      for people who write apps

  The first line on the next screen always says what to do next.
  {_C.BCYAN}?{_C.RST} shows help on any screen, {_C.BCYAN}q{_C.RST} goes back.

  Plug your CrossPad in with a USB cable now.
""")
        self._footer("any key: start")
        _read_key_blocking()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(datetime.now(timezone.utc).isoformat())

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
        """(installed, total_compatible_in_registry).

        Installed counts everything on disk, including apps that are not in the
        registry — a locally generated app is still installed, and a dashboard
        that says 3 above a list of 4 is just wrong.
        """
        compat = [k for k, v in self._apps.items()
                  if self.mgr._is_compatible(v)]
        return len(self._installed), len(compat)

    # -- rendering helpers ----------------------------------------------------

    def _header(self, title: str, right: str = ""):
        global _screen_title
        _screen_title = title
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
        global _screen_hints
        _screen_hints = hints
        _w(f"\n  {_C.GRAY}{hints}   [?] help{_C.RST}\n")

    def _help(self, title: str, hints: str):
        """What `?` shows: this screen's keys, the rules everywhere, the marks."""
        _clear()
        self._header(f"Help — {title}" if title else "Help")
        keys = [h.strip() for h in _re.split(r"\s{3,}", hints) if h.strip()]
        if keys:
            self._section("Keys on this screen")
            for k in keys:
                _w(f"   {k}\n")
        self._section("Everywhere")
        for k, what in (("↑ ↓", "move — arrows and numbers always work, letters are shortcuts"),
                        ("Enter", "do the highlighted thing"),
                        ("q or Esc", "one screen back (on the first screen: quit)"),
                        ("?", "this help"),
                        ("Ctrl+C", "stops a running build or flash, not the whole tool")):
            _w(f"   {_C.BCYAN}{k:<10}{_C.RST} {what}\n")
        self._section("What the marks mean")
        _w(f"   {G['ok']} fine   {G['fail']} needs you   {G['warn']} worth a look   "
           f"{G['next']} next / working   {G['dot_on']} installed   {G['dot_off']} not installed\n")
        self._section("If the screen is hard to read")
        _w("   NO_COLOR=1         no colours\n"
           "   CROSSPAD_PLAIN=1   plain text, one screen after another (screen readers)\n")
        _w(f"\n  {_C.GRAY}Any key: back{_C.RST}")
        global _help_suspended
        _help_suspended = True
        try:
            _read_key_blocking()
        finally:
            _help_suspended = False

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
        painted = False
        while True:
            if self._stale and painted:
                # Second pass: the frame from before the action is already on
                # screen, so the wait for git and the device probe happens
                # where nobody is staring at a dead terminal.
                self._reload(force_env=(self._stale == "force"))
                self._stale = False
            _clear()
            self._header("CrossPad", self._header_right())
            if self._toast:
                _w(f"\n   {_C.BGREEN}{G['ok']}{_C.RST} {self._toast}\n")
                self._toast = ""

            nxt = self._next
            self._section("What's next")
            _w(f" {_C.BYELLOW}{G['next']}{_C.RST} {_C.BWHITE}{nxt['line']}{_C.RST}\n")
            if nxt["action"] == "update":
                w = self._cols
                for a, r in self._rows.items():
                    if r["state"] != "update":
                        continue
                    changes = change_summary(self._statuses[a], self.mgr.available(a))
                    if changes:
                        more = f" (+{len(changes) - 2} more)" if len(changes) > 2 else ""
                        line = f"{self.mgr.app_display_name(a)}: {'; '.join(changes[:2])}{more}"
                        _w(f"   {_C.GRAY}{line[:w - 5]}{_C.RST}\n")
                    if follow_rule(self._statuses[a]["policy"])[0] == "development":
                        _w(f"   {_C.GRAY}  (development version — newest work, "
                           f"may be unfinished){_C.RST}\n")
                _w(f"   {_C.BCYAN}[Enter]{_C.RST} Update my CrossPad "
                   f"{_C.GRAY}— download, build, flash"
                   f"{self._fmt_estimate(nxt['estimate'])}{_C.RST}\n")
            elif nxt["action"] == "wrong":
                _w(f"   {_C.BCYAN}[Enter]{_C.RST} Something's wrong "
                   f"{_C.GRAY}— see what to do{_C.RST}\n")
            elif nxt["action"] == "resume":
                _w(f"   {_C.BCYAN}[Enter]{_C.RST} Continue from there   "
                   f"{_C.BCYAN}[1]{_C.RST} start over   {_C.BCYAN}[3]{_C.RST} Something's wrong\n")

            self._section("Apps on your CrossPad")
            if not self._installed:
                _w(f"   {_C.GRAY}No apps yet — press 2 to add some.{_C.RST}\n")
            rows_h = max(_get_size()[1] - 14, 3)
            names = list(self._installed)
            start, end = _viewport(0, len(names), rows_h)
            for a in names[start:end]:
                r = self._rows[a]
                name = self.mgr.app_display_name(a)
                if r["state"] == "update":
                    tail = f"{r['installed']} {G['arrow']} {_C.BGREEN}{r['available']}{_C.RST}"
                elif r["state"] == "own":
                    tail = f"{r['installed']:<8} {_C.GRAY}your own copy{_C.RST}"
                elif r["state"] == "changes":
                    tail = f"{r['installed']:<8} {_C.BYELLOW}your changes{_C.RST}"
                elif r["state"] == "missing":
                    tail = f"{_C.BRED}missing on disk — [2] to repair{_C.RST}"
                elif r["state"] == "broken":
                    tail = f"{_C.BRED}broken — [2] to repair{_C.RST}"
                else:
                    tail = f"{r['installed']:<8} {_C.GRAY}up to date{_C.RST}"
                _w(f"   {name:<16} {tail}\n")
            if end < len(names):
                _w(f"   {_C.GRAY}… {len(names) - end} more — press 2{_C.RST}\n")

            _w("\n")
            _w(f" {_C.BCYAN}[1]{_C.RST} Update my CrossPad     "
               f"{_C.BCYAN}[2]{_C.RST} Add or remove apps\n")
            _w(f" {_C.BCYAN}[3]{_C.RST} Something's wrong      "
               f"{_C.BCYAN}[4]{_C.RST} Developer tools\n")
            _w(f" {_C.BCYAN}[q]{_C.RST} Quit                   {_C.BCYAN}[?]{_C.RST} Help   "
               f"{_C.BCYAN}[/]{_C.RST} Find an action\n")
            global _screen_hints
            _screen_hints = ("[1] Update my CrossPad — download, build, flash, check   "
                             "[2] Add or remove apps, or pick a version   "
                             "[3] Something's wrong — every check, with its fix   "
                             "[4] Developer tools   [/] find any action by name   [q] Quit")

            # Everything below returns to a dashboard drawn from what we
            # already know; the refresh happens at the top of the next pass,
            # after the frame is on screen.
            painted = True
            if self._stale:
                continue          # draw the fresh numbers before waiting for a key

            key = ""
            while not self._stale:
                key = _read_key(timeout=0.5 if self._checking else None)
                if key:
                    break
            if not key or key == "resize":
                continue
            if key in ("q", "ctrl-c", "esc"):
                break
            elif key == "enter" and nxt["action"] == "resume":
                self._wait_background()
                failed = next(n for n, t in STEP_TITLES.items() if t == self._dashboard_ctx()["unfinished"])
                self._update_pipeline(resume_from=failed)
                self._stale = "force"
            elif key == "1" or (key == "enter" and nxt["action"] == "update"):
                self._wait_background()
                self._update_pipeline()
                self._stale = "force"
            elif key == "/":
                self._palette()
                self._stale = "force"
            elif key == "2":
                self._wait_background()
                self._apps_screen()
                self._stale = True
            elif key == "3" or (key == "enter" and nxt["action"] == "wrong"):
                self._something_wrong()
                self._stale = True
            elif key == "4":
                self._wait_background()
                self._developer_tools()
                self._stale = "force"

    def _actions(self) -> list[tuple[str, str, object]]:
        """Every action CP Tools has, flat: what `/` searches."""
        out = [("Update my CrossPad", "download, build, flash, check", self._update_pipeline),
               ("Add or remove apps", "and pick a version for each", self._apps_screen),
               ("Something's wrong", "every check, with its fix", self._something_wrong),
               ("Report for support", "one zip with logs and findings", self._support_flow),
               ("Go back to the versions from before", "undo the last update", self._go_back_flow),
               ("Previous firmware", "switch the board to its second slot", self._switch_slot_flow)]
        for title, what, fn in self._dev_entries():
            out.append((title, what, fn))
        return out

    def _palette(self):
        search, cursor = "", 0
        global _help_suspended
        while True:
            acts = [a for a in self._actions()
                    if search.lower() in (a[0] + " " + a[1]).lower()]
            cursor = min(cursor, max(len(acts) - 1, 0))
            _clear()
            self._header("Find an action", "type to filter")
            _w(f"\n  {_C.BYELLOW}/{_C.RST} {_C.BWHITE}{search}{_C.RST}\n\n")
            for i, (title, what, _fn) in enumerate(acts[:max(_get_size()[1] - 8, 3)]):
                mark = f"{_C.BYELLOW}>{_C.RST}" if i == cursor else " "
                _w(f" {mark} {title:<38} {_C.GRAY}{what}{_C.RST}\n")
            if not acts:
                _w(f"   {_C.GRAY}No matches for '{search}'{_C.RST}\n")
            self._footer("type to filter   ↑↓ pick   [Enter] run   [Esc] back")
            _help_suspended = True
            try:
                key = _read_key()
            finally:
                _help_suspended = False
            if key in ("esc", "ctrl-c"):
                return
            if key == "up" and acts:
                cursor = (cursor - 1) % len(acts)
            elif key == "down" and acts:
                cursor = (cursor + 1) % len(acts)
            elif key == "enter" and acts:
                acts[cursor][2]()
                return
            elif key == "backspace":
                search = search[:-1]
            elif len(key) == 1 and key.isprintable():
                search += key

    def _update_pipeline(self, resume_from: str | None = None):
        ui = _PipelineUI(self)
        pipe = UpdatePipeline(self.mgr, ui)
        start = resume_from if resume_from in [s.name for s in pipe.steps] else None
        ok = pipe.retry_from(start) if start else pipe.run()
        while True:
            ui.render(pipe.steps, pipe.tail, None)
            failed = next((s for s in pipe.steps if s.ok is False), None)
            if ok:
                _w(f"\n {_C.BGREEN}{G['ok']} Your CrossPad is up to date.{_C.RST}"
                   f"   {_C.GRAY}[q] back{_C.RST}\n")
            else:
                global _screen_hints
                _screen_hints = (f"[r] retry from {STEP_TITLES[failed.name] if failed else 'the start'}"
                                 f"   [c] show the error   [s] save a report for support"
                                 f"   [3] Something's wrong   [q] back")
                _w(f"\n {_C.GRAY}{_screen_hints}   [?] help{_C.RST}\n")
            key = _read_key()
            if key in ("q", "esc", "ctrl-c", "enter") and (ok or key != "enter"):
                return
            if key == "r" and failed:
                ok = pipe.retry_from(failed.name)
            elif key == "c":
                self._show_log_tail()
            elif key == "s" and not ok:
                self._support_flow()
            elif key == "3":
                self._something_wrong()

    def _show_log_tail(self, lines: int = 40):
        _clear()
        self._header("The error", LAST_UPDATE_LOG)
        try:
            tail = (self.mgr.project_dir / LAST_UPDATE_LOG).read_text(
                encoding="utf-8", errors="replace").splitlines()[-lines:]
        except OSError:
            tail = ["(no log yet)"]
        w = _get_size()[0]
        for line in tail:
            col = _C.BRED if "error" in line.lower() else ""
            _w(f" {col}{line[:w - 2]}{_C.RST}\n")
        _pause()

    def _apps_screen(self):
        cursor, search = 0, ""
        while True:
            installed = [a for a in self._installed]
            available = [a for a in self._apps if a not in self._installed]
            if search:
                f = lambda a: search.lower() in self.mgr.app_display_name(a).lower()
                installed, available = [a for a in installed if f(a)], [a for a in available if f(a)]
            items = ([("h", "On your CrossPad")] + [("i", a) for a in installed]
                     + [("h", "Available")] + [("a", a) for a in available])
            sel = [i for i, (k, _) in enumerate(items) if k != "h"]
            if not sel:
                items, sel = [("h", f"No matches for '{search}'")], []
            cursor = min(cursor, max(len(sel) - 1, 0))

            _clear()
            self._header("Add or remove apps",
                         f"type to filter{(' · ' + search) if search else ''} · "
                         f"{len(self._apps)} apps")
            h = max(_get_size()[1] - 7, 3)
            cur_idx = sel[cursor] if sel else 0
            start, end = _viewport(cur_idx, len(items), h)
            w = _get_size()[0]
            for i in range(start, end):
                kind, val = items[i]
                if kind == "h":
                    self._section(val)
                    continue
                info = self._apps.get(val, {})
                name = self.mgr.app_display_name(val)
                compat = self.mgr._is_compatible(info) if info else True
                mark = f"{_C.BYELLOW}>{_C.RST}" if i == cur_idx else " "
                if kind == "i":
                    r = self._rows.get(val, {"installed": "", "state": "current"})
                    note = {"own": "your own copy", "changes": "your changes",
                            "broken": "broken — [Enter] to repair",
                            "update": f"{r.get('available', '')} available"}.get(r["state"], "")
                    _w(f" {mark} {_C.BGREEN}{G['ok']}{_C.RST} {name:<16} {r['installed']:<8} "
                       f"{_C.GRAY}{(note or info.get('description', ''))[:w - 34]}{_C.RST}\n")
                else:
                    col = _C.DIM if not compat else ""
                    why = (f"({', '.join(info.get('platforms', []))} only)"
                           if not compat else info.get("description", ""))
                    _w(f" {mark}   {col}{name:<16} {info.get('version', ''):<8} "
                       f"{_C.GRAY}{why[:w - 34]}{_C.RST}\n")
            self._footer("[Enter] install / open   [x] remove (when not filtering)   "
                         "[backspace] clear filter   [q] back")

            key = _read_key()
            if key in ("q", "esc", "ctrl-c"):
                return
            elif key == "up" and sel:
                cursor = (cursor - 1) % len(sel)
            elif key == "down" and sel:
                cursor = (cursor + 1) % len(sel)
            elif key == "enter" and sel:
                kind, app_id = items[sel[cursor]]
                if kind == "i" and self._rows.get(app_id, {}).get("state") in ("broken", "missing"):
                    self._repair_flow(app_id)
                elif kind == "i":
                    self._app_versions(app_id)
                else:
                    info = self._apps.get(app_id, {})
                    if not self.mgr._is_compatible(info):
                        self._toast_here(f"{self.mgr.app_display_name(app_id)} is for "
                                         f"{', '.join(info.get('platforms', []))}, not this CrossPad")
                        continue
                    self._install_flow(app_id)
                self._reload()
            elif key == "x" and not search and sel and items[sel[cursor]][0] == "i":
                self._remove_flow(items[sel[cursor]][1])
                self._reload()
            elif key == "backspace":
                search = search[:-1]
            elif len(key) == 1 and key.isprintable():
                search += key

    def _toast_here(self, text: str):
        _w(f"\n   {_C.BYELLOW}{text}{_C.RST}\n")
        _pause()

    def _wrong_facts(self) -> dict:
        env = self._env(force=True)
        return self.mgr.doctor_facts(device=env["device"],
                                     gh=(env["gh_ok"], env["gh_user"]))

    def _something_wrong(self):
        cursor = 0
        facts = self._wrong_facts()
        while True:
            rows = wrong_rows(facts)
            _clear()
            self._header("Something's wrong?", self._header_right())
            _w("\n")
            w = _get_size()[0]
            for i, r in enumerate(rows):
                mark, col = {True: (G["ok"], _C.BGREEN), False: (G["fail"], _C.BRED),
                             None: (G["warn"], _C.BYELLOW)}[r["ok"]]
                sel = f"{_C.BYELLOW}>{_C.RST}" if i == cursor else " "
                _w(f" {sel} {col}{mark:<2}{_C.RST}{r['title']:<22} {r['detail'][:w - 30]}\n")
                if r["fix"] and r["ok"] is not True:
                    _w(f"      {' ' * 22} {_C.BCYAN}{r['fix']}{_C.RST}\n")
            self._footer("↑↓ pick   [Enter] do it   [l] open last update log   "
                         "[s] save a report for support   "
                         "[f] flash again via cable (board won't answer)   [q] back")
            key = _read_key()
            if key in ("q", "esc", "ctrl-c"):
                return
            elif key == "up":
                cursor = (cursor - 1) % len(rows)
            elif key == "down":
                cursor = (cursor + 1) % len(rows)
            elif key == "l":
                self._show_log_tail()
            elif key == "s":
                self._support_flow(facts)
            elif key == "f":
                self._recover_flow()
                facts = self._wrong_facts()
            elif key == "enter":
                action = rows[cursor]["action"]
                if action == "update":
                    self._update_pipeline()
                elif action == "usb_guard_off":
                    self.mgr.cdc_verb("USB_GUARD 0")
                elif action == "refresh":
                    _clear()
                    _w(f"\n  {_C.GRAY}Refreshing…{_C.RST}\n")
                    self.mgr.retry_network()
                    self.mgr._fetch_remote_registry()
                    self.mgr.refresh_available(list(self._installed))
                    self._reload()
                elif action == "install_pyserial":
                    _clear()
                    self.mgr.run_command(f'"{sys.executable}" -m pip install --user pyserial')
                    _pause()
                elif action == "go_back":
                    self._go_back_flow()
                elif action == "switch_slot":
                    self._switch_slot_flow()
                elif action == "forget_board":
                    local = self.mgr._load_local_config()
                    local.pop("board", None)
                    self.mgr.save_config(local, local=True)
                elif action == "log":
                    self._show_log_tail()
                facts = self._wrong_facts()

    def _repair_flow(self, app_id: str):
        name = self.mgr.app_display_name(app_id)
        st = self.mgr.app_status(app_id)
        _clear()
        self._header(f"Repair {name}")
        why = st["git"].get("broken") or "the folder is missing"
        _w(f"\n  {name}: {why}.\n\n"
           f"   {_C.BCYAN}[1]{_C.RST} Repair — keep the folder, fetch what is missing\n"
           f"   {_C.BCYAN}[2]{_C.RST} Download again — delete the folder and get a fresh copy\n"
           f"   {_C.GRAY}Either way, anything you changed is backed up first "
           f"({BACKUP_ROOT}).{_C.RST}\n")
        self._footer("[1] repair   [2] download again   [q] back")
        key = _read_key_blocking()
        if key not in ("1", "2"):
            return
        if key == "2" and not _confirm(f"Delete {st['path']} and download it again?"):
            return
        _w(f"\n  {_C.GRAY}Working…{_C.RST}\n")
        ok, msg = self.mgr.repair_app(app_id, fresh=(key == "2"))
        _w(f"\n  {(_C.BGREEN + G['ok']) if ok else (_C.BRED + G['fail'])}{_C.RST} {name}: {msg}\n")
        if not ok:
            _w(f"  {_C.GRAY}[s] on Something's wrong saves a report for support.{_C.RST}\n")
        _pause()
        self._reload()

    def _go_back_flow(self):
        plan = self.mgr.rollback_plan()
        if not plan:
            self._toast_here("Nothing to go back to — the last update changed no app.")
            return
        _clear()
        self._header("Go back to the versions from before")
        _w("\n")
        for app_id, sha in plan.items():
            _w(f"   {self.mgr.app_display_name(app_id):<16} {G['back']} {sha[:8]}\n")
        _w(f"\n  {_C.GRAY}These apps will stay on those versions until you pick "
           f"'Latest release'\n  for them in [2]. Then the firmware is built and "
           f"flashed again.{_C.RST}\n")
        if not _confirm("Go back?"):
            return
        done = self.mgr.roll_back()
        if done:
            self._update_pipeline()

    def _switch_slot_flow(self):
        slot = self.mgr.previous_firmware()
        if not slot:
            self._toast_here("The board has no earlier firmware in its second slot.")
            return
        ver = slot.get("ver", "-")
        _clear()
        self._header("Previous firmware")
        _w(f"\n  The board keeps the firmware it ran before in its second slot"
           f"{f' ({ver})' if ver != '-' else ''}.\n"
           f"  Switching takes seconds and needs no build. Your computer keeps the\n"
           f"  new versions — [1] Update my CrossPad puts them back on later.\n")
        if not _confirm("Switch the board to the previous firmware?"):
            return
        ok = self.mgr.switch_firmware()
        self._toast_here("Switched — the board is restarting." if ok else
                         "The board refused — [s] on Something's wrong saves a report.")

    def _support_flow(self, facts: dict | None = None):
        _clear()
        self._header("Report for support")
        _w(f"\n  {_C.GRAY}Collecting…{_C.RST}\n")
        path = self.mgr.support_bundle(facts)
        _clear()
        self._header("Report for support")
        _w(f"\n  Saved: {_C.BWHITE}{path}{_C.RST}\n\n"
           f"  It holds the last update's log, which apps you have and what this\n"
           f"  screen found — no passwords, no tokens.\n\n"
           f"  Send it on the CrossPad Discord (#support) with one line about what\n"
           f"  you were doing.\n")
        self._footer("[o] open the folder   any other key: back")
        if _read_key_blocking() == "o":
            self._open_url(str(path.parent))

    def _recover_flow(self):
        uart = getattr(self.config, "flash_uart", None)
        dev = self.mgr.device_probe() or {}
        console = ((dev.get("ports") or {}).get("console") or {}).get("path")
        rev = (self.mgr.board_info() or {}).get("rev")
        _clear()
        self._header("Flash again via cable")
        if uart is None or not console or not rev:
            _w(f"\n  {_C.BYELLOW}Can't: "
               f"{'no board' if not console else 'no board revision known' if not rev else 'not on this platform'}"
               f"{_C.RST}\n")
            _pause()
            return
        if not _confirm(f"Reflash {rev} over {console}? The board restarts"):
            return
        _w("\n")
        rc = uart(rev, console, lambda line: _w(f" {_C.DIM}{line[:_get_size()[0] - 2]}{_C.RST}\n"))
        _w(f"\n  {(_C.BGREEN + G['ok']) if rc == 0 else (_C.BRED + G['fail'])}{_C.RST} "
           f"{'flashed' if rc == 0 else 'flash failed — if esptool could not sync, hold BOOT while resetting'}\n")
        _pause()

    def _developer_tools(self):
        entries = self._dev_entries()
        while True:
            idx = _menu_select("Developer tools", [e[0] for e in entries], [e[1] for e in entries])
            if idx < 0:
                return
            entries[idx][2]()
            self._reload()

    def _dev_entries(self) -> list:
        entries = [
            ("Workspace", "per-app ownership: follow rule, git state, backups", self._workspace),
            ("Device", "what the board runs, component by component", self._device),
            ("Browse registry", "every app with details and changelog", self._browse),
            ("Configure", "compile-time feature flags", self._configure),
            ("Profiles", "saved app sets", self._profiles),
            ("Build & Flash", "the raw idf.py / cmake commands", self._build_flash),
            ("OTA Flash", "flash the last build without rebuilding", self._quick_ota),
            ("New app", "scaffold an app from the template", self._new_app_flow),
            ("Registry tools", "refresh, inspect, clear cache, sync manifest", self._registry_tools),
            ("Submit an app to the catalog", "so other CrossPad owners can install it",
             self._submit_flow),
            ("Settings", "update checks, early features", self._settings),
        ]
        if getattr(self.config, "board_revs", None):
            entries.insert(4, ("Board", "choose the board revision to build for",
                               lambda: self._choose_board()))
        return entries

    def _submit_flow(self):
        own = [a for a in self._installed if a not in self._apps]
        if not own:
            self._toast_here("Every app here is already in the catalog. Make one with New app.")
            return
        idx = _menu_select("Which app?", [self.mgr.app_display_name(a) for a in own])
        if idx < 0:
            return
        app_id = own[idx]
        _clear()
        self._header(f"Submit {self.mgr.app_display_name(app_id)}")
        _w(f"\n  {_C.GRAY}Checking…{_C.RST}\n")
        problems, owner_repo, meta = self.mgr.catalog_check(app_id)
        _clear()
        self._header(f"Submit {self.mgr.app_display_name(app_id)}", owner_repo or "")
        if problems:
            _w(f"\n  Not yet:\n")
            for pr in problems:
                _w(f"   {_C.BRED}{G['fail']}{_C.RST} {pr}\n")
            _pause()
            return
        _w(f"\n  This opens a pull request on CrossPad/crosspad-apps that adds\n"
           f"  {owner_repo} to the catalog. Once it is merged, the app shows up\n"
           f"  under [2] for everyone within a few hours.\n")
        if not _confirm("Submit it?"):
            return
        ok, msg = self.mgr.submit_to_catalog(app_id)
        self._toast_here(f"Pull request: {msg}" if ok else f"Couldn't: {msg}")

    def _settings(self):
        cursor = 0
        while True:
            st = self.mgr.settings()
            rows = [("check_updates", "Check for updates when CP Tools starts",
                     "in the background; off: only when you ask ([3] → Registry)"),
                    ("early_features", "Early features",
                     "on: apps that follow the latest release follow development "
                     "instead — newest work, may be unfinished. Versions you picked "
                     "stay put.")]
            _clear()
            self._header("Settings", f"CP Tools {MANAGER_VERSION}")
            _w("\n")
            for i, (key, title, help_) in enumerate(rows):
                sel = f"{_C.BYELLOW}>{_C.RST}" if i == cursor else " "
                val = f"{_C.BGREEN}on{_C.RST}" if st[key] else f"{_C.GRAY}off{_C.RST}"
                _w(f" {sel} {title:<42} {val}\n")
                if i == cursor:
                    _w(f"     {_C.GRAY}{help_}{_C.RST}\n")
            self._footer("↑↓ pick   [Enter] switch   [q] back")
            key = _read_key()
            if key in ("q", "esc", "ctrl-c"):
                return
            if key == "up":
                cursor = (cursor - 1) % len(rows)
            elif key == "down":
                cursor = (cursor + 1) % len(rows)
            elif key in ("enter", " "):
                name = rows[cursor][0]
                if name == "early_features":
                    moved = self.mgr.set_early_features(not st[name])
                    if moved:
                        self._toast_here(f"{len(moved)} app(s) now follow "
                                         f"{'development' if not st[name] else 'the latest release'}"
                                         f" — [1] Update my CrossPad puts that on the board")
                else:
                    self.mgr.set_setting(name, not st[name])

    def _choose_board(self) -> bool:
        revs = list(getattr(self.config, "board_revs", ()))
        if not revs:
            return False
        b = self.mgr.board_info() or {}
        found = {d.get("board_rev") or d.get("fw_rev"): d.get("id") for d in b.get("devices", [])}
        descs = [f"connected: {found[r]}" if r in found else "" for r in revs]
        idx = _menu_select("Board revision", revs, descs)
        if idx < 0:
            return False
        self.config.board_set(revs[idx])
        self.mgr.board_info(refresh=True)
        return True

    # -- New app --------------------------------------------------------------

    def _new_app_flow(self):
        """Form for scaffolding an app, with a preview of what it will create."""
        fields = {
            "id": "",
            "name": "",
            "description": "",
            "category": "tools",
        }
        publish_modes = [
            (None, "local only", "a directory here, tracked as local"),
            ("private", "private GitHub repo",
             "created under your account, installed back as a submodule"),
            ("public", "public GitHub repo",
             "same, but open from the start"),
        ]
        publish_idx = 0
        rows = ["id", "name", "description", "category", "publish", "create"]
        cursor = 0
        error = ""

        while True:
            app_id = fields["id"]
            cls = self.mgr.app_id_to_class(app_id) if app_id else ""
            component = f"{self.config.lib_prefix}{app_id}" if app_id else ""
            install_path = (f"{self.config.lib_dir}/{component}"
                            if component else "")
            visibility, publish_label, publish_help = publish_modes[publish_idx]

            _clear()
            self._header("New App", "from the CrossPad template")
            _w("\n")

            shown = {
                "id": ("App id", app_id or
                       f"{_C.DIM}lowercase-with-dashes{_C.RST}"),
                "name": ("Name", fields["name"] or
                         (f"{_C.DIM}{cls}{_C.RST}" if cls else
                          f"{_C.DIM}—{_C.RST}")),
                "description": ("Description", fields["description"] or
                                f"{_C.DIM}{(fields['name'] or cls) + ' — a CrossPad app' if cls else '—'}{_C.RST}"),
                "category": ("Category", fields["category"]),
                "publish": ("Publish", publish_label),
            }
            for i, key in enumerate(rows):
                marker = f"{_C.BYELLOW}>{_C.RST}" if i == cursor else " "
                if key == "create":
                    ready = self.mgr.valid_app_id(app_id)
                    col = _C.BGREEN if ready else _C.DIM
                    _w(f"\n  {marker} {col}Create{_C.RST}"
                       f"{'' if ready else f'{_C.DIM}   (needs an id: lowercase letters, digits, dashes){_C.RST}'}\n")
                    continue
                label, value = shown[key]
                _w(f"  {marker} {_C.GRAY}{label:<14}{_C.RST}{value}\n")

            if cursor < len(rows) - 1:
                hint = {"id": "lowercase letters, digits and dashes, starting with "
                              "a letter — becomes crosspad-<id>",
                        "name": "shown in the launcher",
                        "description": "one line, lands in crosspad-app.json",
                        "category": "music · audio · tools · other",
                        "publish": publish_help}[rows[cursor]]
                _w(f"\n   {_C.GRAY}{hint}{_C.RST}\n")

            # -- preview --
            if app_id and self.mgr.valid_app_id(app_id):
                self._section("Will create")
                _w(f"   {_C.BWHITE}{install_path}/{_C.RST}\n")
                _w(f"   {_C.GRAY}src/{cls}App.cpp{_C.RST}          "
                   f"LVGL buttons, slider, animation timer\n")
                _w(f"   {_C.GRAY}src/{cls}PadLogic.cpp{_C.RST}      "
                   f"pad handler, off the LVGL thread\n")
                _w(f"   {_C.GRAY}CMakeLists.txt · crosspad-app.json · "
                   f"library.json · README{_C.RST}\n")
                _w(f"\n   registered as {_C.BWHITE}"
                   f"REGISTER_APP_PL({cls}, …){_C.RST}"
                   f"{_C.GRAY} — appears in the launcher{_C.RST}\n")
                if visibility:
                    owner = self._gh_owner()
                    if owner:
                        _w(f"   github.com/{owner}/{component}"
                           f" {_C.GRAY}({visibility}){_C.RST}\n")
                    else:
                        _w(f"   {_C.BYELLOW}Publishing needs a GitHub sign-in:{_C.RST} "
                           f"run {_C.BWHITE}gh auth login{_C.RST} in a terminal, "
                           f"or choose local only\n")
            elif app_id:
                _w(f"\n   {_C.BYELLOW}'{app_id}' is not a valid id{_C.RST}\n")

            if error:
                _w(f"\n   {_C.BYELLOW}{error}{_C.RST}\n")

            self._footer("↑↓ field   enter edit   space cycle publish   "
                         "[c] create   q cancel")

            key = _read_key()
            if key in ("q", "esc", "ctrl-c"):
                return
            elif key == "up":
                cursor = (cursor - 1) % len(rows)
            elif key == "down":
                cursor = (cursor + 1) % len(rows)
            elif key == " " and rows[cursor] == "publish":
                publish_idx = (publish_idx + 1) % len(publish_modes)
            elif key == "enter" and rows[cursor] in fields:
                field = rows[cursor]
                _w("\n")
                _show_cursor()
                value = _text_input(f"  {field}", fields[field])
                _hide_cursor()
                if value is not None:
                    fields[field] = value.strip()
                error = ""
            elif key in ("enter", "c") and (rows[cursor] == "create"
                                            or key == "c"):
                if not self.mgr.valid_app_id(app_id):
                    error = "Enter a valid app id first."
                    continue
                if app_id in self._installed:
                    error = f"'{app_id}' is already installed."
                    continue
                if visibility and not self._gh_owner():
                    error = ("Not signed in to GitHub — run gh auth login in a "
                             "terminal, or set Publish to local only.")
                    continue
                self._create_app(app_id, fields, cls, visibility)
                return

    def _gh_owner(self) -> str:
        if getattr(self, "_gh_owner_cache", None) is None:
            r = subprocess.run(["gh", "api", "user", "--jq", ".login"],
                               capture_output=True, text=True, check=False)
            self._gh_owner_cache = (r.stdout.strip()
                                    if r.returncode == 0 else "")
        return self._gh_owner_cache

    def _create_app(self, app_id: str, fields: dict, cls: str,
                    visibility: str | None):
        """Run the scaffold, showing each step as it completes."""
        steps: list[str] = []

        def render(busy: str = ""):
            _clear()
            self._header(f"Creating {app_id}", "from the CrossPad template")
            _w("\n")
            for done in steps:
                _w(f"   {_C.BGREEN}✓{_C.RST} {done}\n")
            if busy:
                _w(f"   {_C.BYELLOW}·{_C.RST} {busy}...\n")

        def on_step(message: str):
            steps.append(message)
            render()

        render("generating" if not visibility else
               "generating and publishing")
        result = self.mgr.new_app(
            app_id, name=fields["name"], description=fields["description"],
            category=fields["category"] or "tools", visibility=visibility,
            progress=on_step)

        render()
        if not result["ok"]:
            _w(f"\n   {_C.BYELLOW}⚠ {result['error']}{_C.RST}\n")
            self._footer("q back")
            while _read_key() not in ("q", "esc", "enter", "ctrl-c"):
                pass
            return

        self._reload()
        _w(f"\n   {_C.BWHITE}{result['path']}{_C.RST}\n")
        if result.get("repo"):
            _w(f"   {result['repo']}\n")
        _w(f"\n   {_C.GRAY}Rewrite src/{cls}App.cpp and "
           f"src/{cls}PadLogic.cpp — that is the point of it.{_C.RST}\n")

        b = self.mgr.board_info()
        if b is not None and not b.get("rev"):
            if not self._choose_board():
                return
        build_cmd = self._clean_build_command()
        _w(f"\n   {_C.GRAY}A new app directory is only discovered at configure "
           f"time:{_C.RST}\n   {_C.BWHITE}{build_cmd}{_C.RST}\n")
        self._footer("[b] build now   q back")

        while True:
            key = _read_key()
            if key in ("q", "esc", "enter", "ctrl-c"):
                return
            if key == "b":
                _clear()
                _show_cursor()
                self.mgr.run_command(build_cmd)
                _hide_cursor()
                _pause()
                return

    def _clean_build_command(self) -> str:
        if self.config.platform == "esp-idf":
            a = self.mgr.idf_args()
            return f"idf.py {a}fullclean && idf.py {a}build"
        if self.config.platform == "arduino":
            return "pio run --target clean && pio run"
        return "rm -rf build && cmake -B build -G Ninja && cmake --build build"

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
            source = ("--versions on the built binary"
                      if self.config.platform == "pc"
                      else "APP_VERSIONS over CDC")
            self._header("Device", source)

            if report is None:
                _w(f"\n   {_C.GRAY}Querying device...{_C.RST}\n")
                report = self.mgr.device_diff()
                continue

            if not report.get("ok"):
                _w(f"\n   {_C.BYELLOW}⚠{_C.RST} {report.get('error')}\n")
                if self.config.platform != "pc":
                    _w(f"\n   {_C.GRAY}A board in USB audio mode can't answer here. "
                       f"On the pad:\n   Settings → USB → Serial, then [r].{_C.RST}\n")
                self._footer("[r] retry   q back")
            else:
                label = "Binary" if self.config.platform == "pc" else "Port"
                _w(f"\n   {_C.GRAY}{label}{_C.RST}   {report['port']}\n\n")
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
                    _w(f"   {_C.GRAY}Put this checkout on it: [1] Update my CrossPad "
                       f"on the first screen.{_C.RST}\n")
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
            _read_key_blocking()
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
            if info.get("screenshot"):
                acts.append("[p] Picture")
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
            elif key == "p" and info.get("screenshot"):
                shot = info["screenshot"]
                owner_repo = owner_repo_of(repo)
                self._open_url(shot if shot.startswith("http") or not owner_repo
                               else raw_url(owner_repo, shot))
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

        ref = self._latest_ref(app_id, info)

        _w("\n")
        unmet = unmet_requirements(info.get("requires"), self.mgr.component_versions())
        if unmet:
            _w(f"  {_C.BYELLOW}{G['warn']} {name} {'; '.join(unmet)}.{_C.RST}\n"
               f"  {_C.GRAY}It will likely not build until the project's system "
               f"components are updated.{_C.RST}\n")
            if not _confirm(f"Install {name} anyway?"):
                return
        elif not _confirm(f"Install {name}?"):
            return

        _clear()
        self._header(f"Installing {name}...")
        _show_cursor()
        self.mgr.install(app_id, ref=ref, force=True)
        # install()'s own heuristic treats a non-default ref as "the user
        # typed a branch" — a release tag is never == the default branch, so
        # it would land as track=branch here. This screen always means
        # Latest release (spec §4): pin the policy explicitly.
        self.mgr.ensure_config(quiet=True)
        self.mgr.set_app_policy(app_id, TRACK_REGISTRY)
        if self.mgr.settings()["early_features"]:
            path = self.mgr.app_status(app_id)["path"]
            self.mgr.set_app_policy(app_id, TRACK_BRANCH,
                                    ref=self.mgr._get_default_branch(path), local=True)
        self.mgr.refresh_available([app_id])
        _hide_cursor()
        _pause()

    def _latest_ref(self, app_id: str, info: dict) -> str:
        """The registry's version as a tag when the repo has it, else the default branch."""
        ver = info.get("version")
        return f"v{ver}" if ver else "main"

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

    # -- App versions -----------------------------------------------------

    def _app_versions(self, app_id: str) -> bool:
        """One list: follow the latest release, follow development, or a version."""
        cursor = None
        while True:
            st = self.mgr.app_status(app_id)
            avail = self.mgr.available(app_id) or {}
            info = self._apps.get(app_id, {})
            default = avail.get("default_branch") or self.mgr._get_default_branch(st["path"])
            rows = version_rows(st["policy"], default, st["git"]["head"] or "",
                                avail.get("installed_tag"),
                                [tuple(t) for t in avail.get("tags", [])],
                                avail.get("dev_head", "?"), avail.get("dev_behind", 0))
            if cursor is None:
                cursor = next((i for i, r in enumerate(rows) if r.current), 0)

            _clear()
            name = self.mgr.app_display_name(app_id)
            row = self._rows.get(app_id) or app_row(st, avail or None, app_id in self._apps)
            owner = info.get("repo", "").replace("https://github.com/", "").split("/")[0]
            self._header(name, f"installed {row['installed']}"
                               + (f" · by {owner}" if owner else ""))
            if info.get("description"):
                _w(f" {_C.GRAY}{info['description']}{_C.RST}\n")
            self._section("Version")
            h = max(_get_size()[1] - 9, 3)
            start, end = _viewport(cursor, len(rows), h)
            have = self.mgr.component_versions()
            unmet = {}
            for i in range(start, end):
                r = rows[i]
                if r.kind == "version":
                    unmet[i] = unmet_requirements(self.mgr.requires_at(app_id, r.target), have)
                    if unmet[i]:
                        r.detail = f"{r.detail}  needs a newer system"
                mark = f"{_C.BYELLOW}>{_C.RST}" if i == cursor else " "
                dot = G["dot_on"] if r.current else G["dot_off"]
                tags = []
                if r.installed:
                    tags.append(f"{G['back']} installed")
                if r.recommended:
                    tags.append(f"{G['back']} recommended")
                _w(f" {mark} {dot} {r.label:<22} {_C.GRAY}{r.detail:<34}"
                   f"{'  '.join(tags)}{_C.RST}\n")
            if end < len(rows):
                _w(f"     {_C.GRAY}… {len(rows) - end} more{_C.RST}\n")
            self._footer("[Enter] use this version   [c] what changed   "
                         "[x] remove   [q] back")

            key = _read_key()
            if key in ("q", "esc", "ctrl-c"):
                return False
            elif key == "up":
                cursor = (cursor - 1) % len(rows)
            elif key == "down":
                cursor = (cursor + 1) % len(rows)
            elif key == "enter":
                r = rows[cursor]
                if r.kind == "other" and not r.target:
                    r = self._other_commit_flow(app_id)
                    if r is None:
                        continue
                if unmet.get(cursor) and not _confirm(
                        f"{name} {r.label} {unmet[cursor][0]} — it will likely not build. Use it anyway?"):
                    continue
                ok, msg = self.mgr.set_version(app_id, r)
                _clear()
                mark = G["ok"] if ok else G["fail"]
                _w(f"\n  {_C.BGREEN if ok else _C.BRED}{mark}{_C.RST} {name}: {msg}\n")
                if ok and r.kind in ("release", "development"):
                    _w(f"  {_C.GRAY}Update my CrossPad puts it on the board.{_C.RST}\n")
                _pause()
                self._reload()
            elif key == "c":
                self._show_changelog(app_id)
            elif key == "x":
                self._remove_flow(app_id)
                self._reload()
                if app_id not in self._installed:
                    return True

    def _other_commit_flow(self, app_id: str):
        _show_cursor()
        text = _text_input("Commit or tag", "")
        _hide_cursor()
        if not text:
            return None
        return VersionRow("other", text.strip(), text.strip(), "a commit you picked")

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
                if st["blocking"]:
                    dot, col = "●", _C.BYELLOW
                elif st["protected"]:
                    dot, col = "✋", _C.BCYAN
                else:
                    dot, col = "●", _C.BGREEN
                marker = f"{_C.BYELLOW}>{_C.RST}" if i == cursor else " "
                nb = len(self.mgr.list_backups(name))
                rule, target = follow_rule(st["policy"])
                follow = {"release": "follows latest release",
                          "development": f"follows {target}",
                          "version": f"stays on {target[:8]}",
                          "own": "yours"}[rule]
                _w(f"  {marker} {col}{dot}{_C.RST} {name:<16}"
                   f"{_C.GRAY}{follow:<26}{_C.RST} "
                   f"{self.mgr.describe_status(st):<30} "
                   f"{_C.DIM}{('bk:' + str(nb)) if nb else ''}{_C.RST}\n")
                if i == cursor and st["blocking"]:
                    _w(f"      {_C.YELLOW}blocked: "
                       f"{', '.join(st['blocking'])}{_C.RST}\n")

            self._section("Legend")
            _w(f"   {_C.BGREEN}●{_C.RST} clean   "
               f"{_C.BYELLOW}●{_C.RST} local work (updates blocked)   "
               f"{_C.BCYAN}✋{_C.RST} protected by policy\n")

            self._footer("↑↓ navigate   [m] version   [b] backup   "
                         "[r] restore   [p] park WIP   [x] remove   "
                         "[enter] details   q back")

            key = _read_key()
            if key in ("q", "esc", "ctrl-c"):
                return
            elif key == "up":
                cursor = (cursor - 1) % len(statuses)
            elif key == "down":
                cursor = (cursor + 1) % len(statuses)
            elif key == "m":
                self._app_versions(statuses[cursor]["app"])
                self._reload()
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
            elif key == "x":
                if self._remove_app_flow(statuses[cursor]):
                    self._reload()
                    refresh()
                    cursor = min(cursor, max(len(statuses) - 1, 0))
            elif key == "enter":
                self._workspace_detail(statuses[cursor])
                refresh()

    def _remove_app_flow(self, st: dict) -> bool:
        """Uninstall an app, saying up front what happens to local work."""
        app = st["app"]
        _clear()
        self._header(f"Remove {app}")
        _w(f"\n   {_C.GRAY}{st['path']}{_C.RST}\n")
        rule, target = follow_rule(st["policy"])
        follows = {"release": "follows latest release",
                   "development": f"follows {target}",
                   "version": f"stays on {target[:8]}",
                   "own": "yours"}[rule]
        _w(f"   {_C.GRAY}{follows}   "
           f"{self.mgr.describe_status(st)}{_C.RST}\n")

        risky = st["blocking"] or st["git"]["untracked"] or st["git"]["stashes"]
        if risky:
            _w(f"\n   {_C.BYELLOW}This app carries local work"
               f"{(' (' + ', '.join(st['blocking']) + ')') if st['blocking'] else ''}"
               f".{_C.RST}\n")
            _w(f"   {_C.GRAY}It will be backed up to .crosspad/backups/{app}/ "
               f"before removal.{_C.RST}\n")
        if not st["git"]["origin"]:
            _w(f"\n   {_C.BYELLOW}No remote — once removed, the backup is the "
               f"only copy.{_C.RST}\n")

        _w("\n")
        _show_cursor()
        confirmed = _confirm(f"Remove {app}?")
        _hide_cursor()
        if not confirmed:
            return False

        _clear()
        _show_cursor()
        self.mgr.remove(app)
        _hide_cursor()
        _pause()
        return True

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
            rule, target = follow_rule(st["policy"])
            follows = {"release": "follows latest release",
                       "development": f"follows {target}",
                       "version": f"stays on {target[:8]}",
                       "own": "yours"}[rule]
            rows = [
                ("Follows", follows),
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

            self._footer("[m] version   [b] backup   [r] restore   "
                         "[p] park WIP   q back")
            key = _read_key()
            if key in ("q", "esc", "ctrl-c"):
                return
            elif key == "m":
                self._app_versions(st["app"])
                self._reload()
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
                if self._is_board_flag(flag):
                    dim = f"{_C.DIM}(idf.py board — enter changes){_C.RST}"
                elif managed:
                    dim = f"{_C.DIM}(managed by {managed}){_C.RST}"
                else:
                    dim = f"{_C.BYELLOW}*{_C.RST}" if value != default else " "
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
                       f"idf.py {self.mgr.idf_args()}fullclean.{_C.RST}\n")
                _pause()
            elif key == "s":
                self._save_profile_flow()

    def _is_board_flag(self, flag: dict) -> bool:
        """The board-revision flag, on a platform whose wrapper resolves the board."""
        return (flag.get("group") == "board"
                and self.mgr.board_info() is not None)

    def _toggle_flag(self, flag: dict, values: dict):
        name = flag["name"]
        if self._is_board_flag(flag):
            self._choose_board()
            return
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
                key = _read_key_blocking()
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
        key = _read_key_blocking()
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
            b = self.mgr.board_info()
            if b is not None and not b.get("rev"):
                if not self._choose_board():
                    return
            ota_cmd = self.mgr.ota_command()
            build_cmd = f"idf.py {self.mgr.idf_args()}build"
        elif self.config.platform == "arduino":
            # The Arduino firmware has no OTA-over-CDC tool of its own; PlatformIO
            # uploads over USB (the STM bridge's DTR/RTS reach EN and GPIO0).
            ota_cmd = "pio run --target upload"
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
                key = _read_key_blocking()
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
                key = _read_key_blocking()
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
            b = self.mgr.board_info()
            if b is not None and not b.get("rev"):
                if not self._choose_board():
                    return
            a = self.mgr.idf_args()
            commands = [
                ("Full Clean + Build",
                 f"idf.py {a}fullclean && idf.py {a}build"),
                ("Build",
                 f"idf.py {a}build"),
                ("Flash (UART)",
                 f"idf.py {a}{{port}} flash"),
                ("Flash (OTA)",
                 self.mgr.ota_command()),
                ("Monitor",
                 f"idf.py {a}{{port}} monitor"),
                ("Flash + Monitor",
                 f"idf.py {a}{{port}} flash monitor"),
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

    # -- Dev Tools ------------------------------------------------------------

    def _registry_tools(self):
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
