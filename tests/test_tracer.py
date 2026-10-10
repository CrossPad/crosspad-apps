import sys
import time

import pytest

import crosspad_app_manager as cam
from tests.hil_fakes import plain


def test_trace_cli_on_path_wins(monkeypatch, tmp_path):
    monkeypatch.delenv("CROSSPAD_TRACE", raising=False)
    monkeypatch.setattr(cam.shutil, "which",
                        lambda n: "/usr/bin/crosspad-trace" if n == "crosspad-trace" else "/usr/bin/node")
    assert cam.find_trace_cli(tmp_path) == ["/usr/bin/crosspad-trace"]


def test_trace_cli_falls_back_to_the_mcp_checkout(monkeypatch, tmp_path):
    monkeypatch.delenv("CROSSPAD_TRACE", raising=False)
    script = tmp_path / "GIT" / "crosspad-mcp" / "dist" / "trace-cli.js"
    script.parent.mkdir(parents=True)
    script.write_text("")
    monkeypatch.setattr(cam.shutil, "which", lambda n: "/usr/bin/node" if n == "node" else None)
    assert cam.find_trace_cli(tmp_path) == ["/usr/bin/node", str(script)]


def test_no_tracer_says_how_to_get_it(monkeypatch, tmp_path):
    monkeypatch.delenv("CROSSPAD_TRACE", raising=False)
    monkeypatch.setattr(cam.shutil, "which", lambda n: None)
    assert cam.find_trace_cli(tmp_path) is None
    assert "crosspad-mcp" in "\n".join(cam.TRACER_MISSING_LINES)


def test_crosspad_trace_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setattr(cam.shutil, "which", lambda n: "/usr/bin/crosspad-trace")
    monkeypatch.setenv("CROSSPAD_TRACE", str(tmp_path / "not-there"))
    assert cam.find_trace_cli(tmp_path) is None


def test_verdict_names_the_failure_and_keeps_the_doctor_lines():
    doctor = ["doctor: no ST-Link found", "fix: plug the ST-Link in and run crosspad-trace again"]
    v1 = plain(cam.tracer_verdict(1, doctor, False))
    assert "could not reach the STM32" in v1 and "fix: plug the ST-Link in" in v1
    v2 = plain(cam.tracer_verdict(2, ["pyOCD venv missing", "fix: bash tracer/setup.sh"], False))
    assert "not set up" in v2 and "bash tracer/setup.sh" in v2
    assert plain(cam.tracer_verdict(None, doctor, True)) == "  The tracer stopped."
    assert "exit code 7" in plain(cam.tracer_verdict(7, [], False))


def test_tracer_run_keeps_output_and_exit_code():
    run = cam._TracerRun([sys.executable, "-c",
                          "import sys; print('doctor: no ST-Link found'); sys.exit(1)"])
    run.start()
    deadline = time.monotonic() + 10
    while run.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert run.poll() == 1
    assert "doctor: no ST-Link found" in run.lines()


@pytest.mark.skipif(sys.platform == "win32", reason="CTRL_BREAK is sent to a console group")
def test_stopping_the_tracer_interrupts_it_like_ctrl_c():
    run = cam._TracerRun([sys.executable, "-c",
                          "import time\ntry:\n    time.sleep(30)\n"
                          "except KeyboardInterrupt:\n    print('stopped cleanly')"])
    run.start()
    time.sleep(1.0)
    t0 = time.monotonic()
    run.stop()
    assert time.monotonic() - t0 < 5
    assert "stopped cleanly" in run.lines()


def test_tracer_output_cannot_drive_the_terminal():
    run = cam._TracerRun([sys.executable, "-c",
                          "print('dash\\x1b[2Jboard\\x1b]0;x\\x07end', flush=True)"])
    run.start()
    deadline = time.monotonic() + 10
    while run.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    text = "\n".join(run.lines())
    assert "\x1b" not in text and "\x07" not in text and "dash" in text and "end" in text


def test_the_tracer_is_stopped_when_the_screen_fails(monkeypatch):
    runs = []

    class Recorded(cam._TracerRun):
        def __init__(self, argv):
            super().__init__(argv)
            runs.append(self)

    def boom(_timeout):
        raise RuntimeError("terminal went away")

    monkeypatch.setattr(cam, "find_trace_cli",
                        lambda: [sys.executable, "-c", "import time; time.sleep(30)"])
    monkeypatch.setattr(cam, "_TracerRun", Recorded)
    monkeypatch.setattr(cam, "_read_key", boom)
    host = type("Host", (), {"_header": lambda *a: None, "_footer": lambda *a: None,
                             "_toast_here": lambda *a: None, "_cols": 80})()
    with pytest.raises(RuntimeError):
        cam._TUI._tracer_stm(host)
    assert runs and runs[0].poll() is not None
