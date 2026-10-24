import crosspad_app_manager as cam
from tests.hil_fakes import DEV, FakeHil

APPVER = {"components": [
    {"component": "crosspad-sampler", "id": "sampler", "commit": "b048ab8", "ref": "v0.7.0", "dirty": True},
    {"component": "crosspad-core", "id": None, "commit": "4ac6d69", "ref": "main", "dirty": False}],
    "count": 2, "libver": {}, "board": {}}
HOLDER = {"client": "crosspad-hil", "purpose": "kit_churn", "pid": 4121, "since": 1}


def mgr_with(tmp_path, table):
    mgr = cam.AppManager(str(tmp_path), cam.PlatformConfig(platform="esp-idf"))
    mgr._hil = FakeHil(table)
    return mgr


def test_device_versions_come_through_hil(tmp_path):
    mgr = mgr_with(tmp_path, {"cdc.verb:app_versions": {"result": APPVER},
                              "devices.list": {"result": {"devices": [DEV]}}})
    r = mgr.query_device_versions()
    assert r["ok"] and r["port"] == "/dev/ttyACM0" and r["error"] == ""
    assert r["entries"][0] == {"component": "crosspad-sampler", "id": "sampler",
                               "commit": "b048ab8", "ref": "v0.7.0", "dirty": "1"}
    assert r["entries"][1]["id"] == "-" and r["entries"][1]["dirty"] == "0"


def test_without_hil_every_answer_is_unknown_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("CROSSPAD_HIL", str(tmp_path / "not-there"))
    mgr = cam.AppManager(str(tmp_path), cam.PlatformConfig(platform="esp-idf"))
    r = mgr.query_device_versions()
    assert not r["ok"] and "crosspad-hil" in r["error"]
    assert mgr.cdc_verb("USB_GUARD") is None
    assert mgr.fw_slots() is None
    assert mgr.switch_firmware() is False


def test_cdc_verb_returns_the_reply_line(tmp_path):
    mgr = mgr_with(tmp_path, {"cdc.transact": {"result": {
        "line": "USB_GUARD: 1", "parsed": None, "rtt_ms": 3.0, "extra_lines": []}}})
    assert mgr.cdc_verb("USB_GUARD") == "USB_GUARD: 1"
    assert mgr._hil.calls[-1] == ("cdc.transact", {"cmd": "USB_GUARD", "timeout_s": 4.0,
                                                   "holder": "cp-tools"})


def test_every_board_call_names_the_bench_holder(tmp_path, monkeypatch):
    mgr = mgr_with(tmp_path, {"cdc.verb:fw_switch": {"result": {"ok": True}},
                              "devices.list": {"result": {"devices": [DEV]}}})
    monkeypatch.setenv("CROSSPAD_BENCH_HOLDER", "pidf")
    mgr.switch_firmware()
    mgr.hil_call("devices.list")
    assert mgr._hil.calls[0][1]["holder"] == "pidf"
    assert "holder" not in mgr._hil.calls[1][1]


def test_a_claimed_bench_reads_as_busy(tmp_path):
    err = {"code": "BENCH_BUSY", "message": "dev_6dd8 is claimed by pidf (firmware_app)",
           "hint": None, "details": {"holder": "pidf", "purpose": "firmware_app"}}
    r = mgr_with(tmp_path, {"cdc.verb:app_versions": {"error": err}}).query_device_versions()
    assert not r["ok"] and r["error"] == "busy: dev_6dd8 is claimed by pidf (firmware_app)"


def test_fw_slots_keep_their_shape_for_previous_firmware(tmp_path):
    slots = {"slots": [
        {"slot": "A", "running": True, "state": "confirmed", "pkg": "sampler", "ver": "v1.2.0", "kit": "sampler"},
        {"slot": "B", "running": False, "state": "installed", "pkg": None, "ver": "v1.1.0", "kit": None}],
        "rollback": True}
    mgr = mgr_with(tmp_path, {"cdc.verb:fw_slots": {"result": slots}})
    assert mgr.previous_firmware() == {"slot": "B", "running": "0", "state": "installed",
                                       "pkg": "-", "ver": "v1.1.0", "kit": "-"}


def test_switch_firmware_is_the_named_verb(tmp_path):
    mgr = mgr_with(tmp_path, {"cdc.verb:fw_switch": {"result": {"ok": True, "reboot": True}}})
    assert mgr.switch_firmware() is True
    assert mgr._hil.verb_calls("fw_switch") == [{}]


def test_a_chosen_board_is_named_in_every_board_call(tmp_path):
    mgr = mgr_with(tmp_path, {"cdc.transact": {"result": {"line": "USB_GUARD: 0"}}})
    mgr.chosen_device = "dev_31ea"
    mgr.cdc_verb("USB_GUARD")
    assert mgr._hil.calls[-1][1]["device"] == "dev_31ea"


def test_a_busy_board_reads_as_busy(tmp_path):
    err = {"code": "PORT_BUSY", "message": "kit_churn holds the board", "hint": None,
           "details": {"holder": HOLDER}}
    r = mgr_with(tmp_path, {"cdc.verb:app_versions": {"error": err}}).query_device_versions()
    assert not r["ok"] and r["error"] == "busy: kit_churn holds the board"


def test_a_screen_client_is_reused_and_left_open(tmp_path):
    mgr = mgr_with(tmp_path, {"cdc.transact": {"result": {"line": "USB_GUARD: 0"}}})
    client = mgr._hil
    mgr.cdc_verb("USB_GUARD")
    assert mgr._hil is client and client.alive
