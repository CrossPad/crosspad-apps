import json
import sys
import time
from pathlib import Path

import pytest

import crosspad_app_manager as cam

FAKE = Path(__file__).with_name("fake_hil_serve.py")
HOLDER = {"client": "crosspad-hil", "purpose": "kit_churn", "pid": 4121, "since": 1}


@pytest.fixture
def serve(tmp_path, monkeypatch):
    made = []

    def make(table):
        path = tmp_path / "table.json"
        path.write_text(json.dumps(table))
        monkeypatch.setenv("FAKE_HIL_TABLE", str(path))
        client = cam._HilClient([sys.executable, str(FAKE)])
        client.start()
        made.append(client)
        return client

    yield make
    for client in made:
        client.close()


def test_request_returns_the_result(serve):
    c = serve({"hub.status": {"result": {"running": True, "clients": [], "lease": None}}})
    assert c.request("hub.status", timeout=10)["running"] is True


def test_answers_are_matched_by_id_not_by_order(serve):
    c = serve({"slow": {"sleep": 0.5, "result": "slow"}, "fast": {"result": "fast"}})
    slow, fast = c.submit("slow"), c.submit("fast")
    assert fast.result(10) == "fast"
    assert not slow.done()
    assert slow.result(10) == "slow"


def test_an_error_carries_code_and_holder(serve):
    c = serve({"cdc.verb": {"error": {"code": "PORT_BUSY", "message": "busy", "hint": None,
                                      "details": {"holder": HOLDER}}}})
    with pytest.raises(cam.HilFailure) as e:
        c.request("cdc.verb", {"verb": "led_state"}, timeout=10)
    assert e.value.code == "PORT_BUSY" and e.value.holder == HOLDER


def test_holder_at_the_top_level_is_found_too():
    err = cam.HilFailure.from_wire({"code": "PORT_BUSY", "message": "m", "hint": None, "holder": HOLDER})
    assert err.holder == HOLDER


def test_a_timeout_is_a_hil_failure_not_a_hang(serve):
    c = serve({"slow": {"sleep": 3, "result": 1}})
    t0 = time.monotonic()
    with pytest.raises(cam.HilFailure) as e:
        c.request("slow", timeout=0.3)
    assert e.value.code == "TIMEOUT" and time.monotonic() - t0 < 2


def test_a_dead_serve_fails_what_waits_and_names_stderr(serve):
    c = serve({})
    with pytest.raises(cam.HilFailure) as e:
        c.request("die", timeout=10)
    assert e.value.code == cam.HIL_EXITED and "going away" in e.value.message
    assert not c.alive
    with pytest.raises(cam.HilFailure) as again:
        c.request("hub.status", timeout=1)
    assert again.value.code == cam.HIL_EXITED


def test_children_stay_out_of_the_terminals_ctrl_c(monkeypatch):
    seen = {}

    def fake_popen(argv, **kw):
        seen.update(kw)
        raise OSError("no such program")

    monkeypatch.setattr(cam.subprocess, "Popen", fake_popen)
    with pytest.raises(cam.HilFailure) as e:
        cam._HilClient(["crosspad-hil", "serve"]).start()
    assert e.value.code == cam.HIL_MISSING
    assert seen.get("start_new_session") is True or "creationflags" in seen


def test_bench_holder_is_cp_tools_unless_the_machine_names_one(monkeypatch):
    monkeypatch.delenv("CROSSPAD_BENCH_HOLDER", raising=False)
    assert cam.bench_holder() == "cp-tools"
    monkeypatch.setenv("CROSSPAD_BENCH_HOLDER", "pidf")
    assert cam.bench_holder() == "pidf"


def test_find_hil_order(tmp_path, monkeypatch):
    monkeypatch.delenv("CROSSPAD_HIL", raising=False)
    monkeypatch.setattr(cam.shutil, "which", lambda name: None)
    proj = tmp_path / "proj"
    assert cam.find_hil(proj, home=tmp_path) is None
    home_venv = tmp_path / ".venvs" / "crosspad-hil" / "bin"
    home_venv.mkdir(parents=True)
    (home_venv / "crosspad-hil").write_text("")
    assert cam.find_hil(proj, home=tmp_path) == str(home_venv / "crosspad-hil")
    proj_venv = proj / ".venv" / "Scripts"
    proj_venv.mkdir(parents=True)
    (proj_venv / "crosspad-hil.exe").write_text("")
    assert cam.find_hil(proj, home=tmp_path) == str(proj_venv / "crosspad-hil.exe")
    monkeypatch.setattr(cam.shutil, "which", lambda name: "/usr/local/bin/crosspad-hil")
    assert cam.find_hil(proj, home=tmp_path) == "/usr/local/bin/crosspad-hil"


def test_crosspad_hil_env_overrides_discovery(tmp_path, monkeypatch):
    monkeypatch.setattr(cam.shutil, "which", lambda name: "/usr/local/bin/crosspad-hil")
    monkeypatch.setenv("CROSSPAD_HIL", str(tmp_path / "not-there"))
    assert cam.find_hil(tmp_path, home=tmp_path) is None
    exe = tmp_path / "hil"
    exe.write_text("")
    monkeypatch.setenv("CROSSPAD_HIL", str(exe))
    assert cam.find_hil(tmp_path, home=tmp_path) == str(exe)


def test_board_text_cannot_drive_the_terminal(serve):
    """A file name on the card, an SSID or a trace line comes from outside; an
    escape sequence in it must not reach the screen as one."""
    c = serve({
        "cdc.verb": {"result": {"entries": [{"name": "kit\x1b[2J\x1b]52;c;cHduZWQ=\x07.wav"}],
                                "ssid": "net\x9b31m"}},
        "bad": {"error": {"code": "TIMEOUT", "message": "late\x1b[1A", "details": {}}},
    })
    r = c.request("cdc.verb", timeout=10)
    assert "\x1b" not in r["entries"][0]["name"] and "\x07" not in r["entries"][0]["name"]
    assert "\x9b" not in r["ssid"]
    assert r["entries"][0]["name"].startswith("kit") and r["entries"][0]["name"].endswith(".wav")
    with pytest.raises(cam.HilFailure) as e:
        c.request("bad", timeout=10)
    assert "\x1b" not in e.value.message
