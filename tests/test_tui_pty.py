"""Every screen of the real TUI, driven through a pseudo-terminal.

What the unit tests cannot see: a screen that crashes on draw, a key that
lands on the wrong method. Runs on Linux and macOS (no pty on Windows),
offline, against a throwaway project.
"""
import json
import os
import re
import select
import subprocess
import sys
import time

import pytest

pty = pytest.importorskip("pty")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWN, ENTER, ESC = "\x1b[B", "\r", "\x1b"


@pytest.fixture
def project(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "apps.json").write_text(json.dumps({"installed": {}}))
    (tmp_path / "app-registry.json").write_text(json.dumps({"version": 1, "apps": {
        "sampler": {"name": "Sampler", "version": "0.2.1", "description": "pads",
                    "repo": "https://github.com/CrossPad/crosspad-sampler.git",
                    "platforms": ["pc"], "category": "music"}}}))
    return tmp_path


def drive(cwd, keys, settle=1.2):
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(cwd)
        env = dict(os.environ, TERM="xterm", PYTHONPATH=ROOT, CROSSPAD_NO_MOUSE="")
        os.execvpe(sys.executable, [sys.executable, "-c",
                   "import crosspad_app_manager as c; c.tui_main(c.PlatformConfig(platform='pc', lib_dir='src/apps'))"],
                   env)
    import fcntl, struct, termios
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
    out = b""

    def pump(t):
        nonlocal out
        end = time.time() + t
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.05)
            if r:
                try:
                    out += os.read(fd, 65536)
                except OSError:
                    return

    pump(2.5)
    for k in keys:
        os.write(fd, k.encode())
        pump(settle)
    try:
        os.kill(pid, 9)
        os.waitpid(pid, 0)
    except OSError:
        pass
    return re.sub(r"\x1b\[[0-9;?<]*[A-Za-z]", "", out.decode("utf-8", "replace"))


def test_every_screen_draws_and_goes_back(project):
    keys = [ENTER,                                   # welcome
            "?", "x",                                # help on the dashboard
            "3", "?", "x", "q",                      # something's wrong
            "2", DOWN, "q",                          # apps
            "/", "set", ENTER, "q",                  # find an action → settings
            "q"]
    text = drive(project, keys)
    assert "Traceback" not in text, text[text.find("Traceback"):][:2000]
    for seen in ("Welcome to CP Tools", "What's next", "Keys on this screen",
                 "Something's wrong", "Add or remove apps", "Find an action", "Settings"):
        assert seen in text, seen


def test_every_developer_tool_opens_and_closes(project):
    drive(project, [ENTER, "q"])                     # the welcome screen, once
    seen = ""
    for i in range(12):
        text = drive(project, ["4"] + [DOWN] * i + [ENTER, "q", "q", "q"], settle=0.6)
        assert "Traceback" not in text, text[text.find("Traceback"):][:2000]
        seen += text
    for title in ("Workspace", "Device", "Browse Apps", "Configure", "Profiles",
                  "Build & Flash", "Run Simulator", "New App", "Registry",
                  "Settings"):
        assert title in seen, title
