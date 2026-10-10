import pytest

import crosspad_app_manager as cam
from tests.hil_fakes import (BASE, DEV, HUB, HUB_LEASED, LEDS, PORT_BUSY_ERR, FakeHil,
                             make_screen, plain, settle)


@pytest.fixture(autouse=True)
def truecolor(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(cam, "PLAIN", False)
    monkeypatch.setenv("COLORTERM", "truecolor")


def test_shift_tab_is_a_key(monkeypatch):
    tail = iter(["[", "Z"])
    monkeypatch.setattr(cam, "_read_within", lambda timeout: next(tail, None))
    assert cam._decode_key("\x1b") == "shift-tab"


def test_pads_show_app_focus_and_the_grid():
    s = make_screen(FakeHil(BASE))
    settle(s)
    text = plain(s.render(100, 30))
    assert "v2 · CDC · bench: free · hub: 2 clients · lease: -" in text
    assert "Sampler" in text and "KIT" in text
    assert "\x1b[48;2;255;0;0m" in "".join(s.render(100, 30))


def test_pads_refresh_at_five_hertz():
    t = [100.0]
    fake = FakeHil(BASE)
    s = make_screen(fake, t=t)
    settle(s)
    before = len(fake.verb_calls("led_state"))
    for step in range(1, 22):              # just over a second, ticked like the key loop
        t[0] = 100.0 + step * 0.05
        s.tick()
    assert len(fake.verb_calls("led_state")) - before == 5


def test_a_key_hits_a_pad_and_lets_go_after_120_ms():
    t = [100.0]
    fake = FakeHil(BASE)
    s = make_screen(fake, t=t)
    settle(s)
    assert s.handle_key("1")
    assert fake.verb_calls("pad_press") == [{"idx": 12, "vel": 100}]
    t[0] = 100.05
    s.tick()
    assert fake.verb_calls("pad_release") == []
    t[0] = 100.2
    s.tick()
    assert fake.verb_calls("pad_release") == [{"idx": 12}]


def test_shift_holds_until_pressed_again():
    t = [100.0]
    fake = FakeHil(BASE)
    s = make_screen(fake, t=t)
    settle(s)
    s.handle_key("!")
    t[0] = 101.0
    s.tick()
    assert fake.verb_calls("pad_release") == [] and s.held == {12}
    assert "1*" in plain(s.render(100, 30))
    s.handle_key("1")
    assert fake.verb_calls("pad_release") == [{"idx": 12}] and s.held == set()


def test_leaving_lets_go_of_every_pad():
    fake = FakeHil(BASE)
    s = make_screen(fake)
    settle(s)
    s.handle_key("Q")                       # held: pad 8
    s.handle_key("z")                       # hit: pad 0, release still pending
    assert s.handle_key("esc") is False
    s.leave()
    assert sorted(a["idx"] for a in fake.verb_calls("pad_release")) == [0, 8]


def test_arrows_turn_the_knob_and_enter_presses_it():
    fake = FakeHil(BASE)
    s = make_screen(fake)
    settle(s)
    s.handle_key("left")
    s.handle_key("right")
    s.handle_key("enter")
    assert fake.verb_calls("enc_rotate") == [{"delta": -1}, {"delta": 1}]
    assert fake.verb_calls("enc_press") == [{}]


def test_app_list_starts_an_app(monkeypatch):
    fake = FakeHil({**BASE, "cdc.verb:app_list": {"result": {"apps": ["Sampler", "Mixer"],
                                                             "running": "Sampler"}}})
    s = make_screen(fake)
    settle(s)
    seen = {}

    def pick(title, items, descriptions=None, hotkeys=None):
        seen["items"] = items
        return 1
    monkeypatch.setattr(cam, "_menu_select", pick)
    s.handle_key("l")
    assert seen["items"][0].startswith("Sampler") and "running" in seen["items"][0]
    assert seen["items"][-1] == "Stop the running app"
    assert fake.verb_calls("app_start") == [{"name": "Mixer"}]


def test_tabs_tab_and_shift_tab_everywhere_digits_off_pads():
    fake = FakeHil(BASE)
    s = make_screen(fake)
    settle(s)
    s.handle_key("2")
    assert s.tab == cam.DEV_TAB_PADS and fake.verb_calls("pad_press") == [{"idx": 13, "vel": 100}]
    s.handle_key("tab")
    assert s.tab == cam.DEV_TAB_TRACE
    s.handle_key("4")
    assert s.tab == cam.DEV_TAB_CONN
    s.handle_key("shift-tab")
    assert s.tab == cam.DEV_TAB_FILES
    s.handle_key("1")
    assert s.tab == cam.DEV_TAB_PADS
    assert s.handle_key("q") is True        # a pad here, not "back"
    s.handle_key("tab")
    assert s.handle_key("q") is False       # "back" on the other tabs


def test_port_busy_shows_the_holder_greys_the_keys_and_recovers():
    t = [100.0]
    table = {**BASE, "hub.status": {"result": HUB_LEASED},
             "cdc.verb:led_state": {"error": PORT_BUSY_ERR},
             "cdc.verb:ui_state": {"error": PORT_BUSY_ERR},
             "cdc.verb:enc_focus": {"error": PORT_BUSY_ERR}}
    fake = FakeHil(table)
    s = make_screen(fake, t=t)
    settle(s)
    lines = s.render(100, 30)
    text = plain(lines)
    assert "lease: kit_churn (pid 4121, 3 min)" in text
    assert "crosspad-hil (kit_churn), pid 4121, for 3 min" in text
    assert "\x1b[48;" not in "".join(lines)
    s.handle_key("1")
    assert fake.verb_calls("pad_press") == []
    assert "Waiting for the board" in plain(s.render(100, 30))
    fake.table.update(BASE)                 # the lease is gone
    t[0] = 101.1
    s.tick()
    s.tick()
    lines = s.render(100, 30)
    assert "The board is busy" not in plain(lines)
    assert "\x1b[48;2;255;0;0m" in "".join(lines)


def test_busy_without_a_lease_retries_once_a_second():
    t = [100.0]
    lock = {"code": "PORT_BUSY", "message": "/dev/ttyACM0 is held by pid 77", "hint": None,
            "details": {}}
    fake = FakeHil({**BASE, "cdc.verb:led_state": {"error": lock},
                    "cdc.verb:ui_state": {"error": lock}, "cdc.verb:enc_focus": {"error": lock}})
    s = make_screen(fake, t=t)
    settle(s)
    assert "held by pid 77" in plain(s.render(100, 30))
    probes = len(fake.verb_calls("ui_state"))
    t[0] = 100.5
    s.tick()
    t[0] = 101.0
    s.tick()
    assert len(fake.verb_calls("ui_state")) == probes + 1


def test_audio_profile_blocks_trace_and_files_not_pads():
    fake = FakeHil({**BASE, "devices.list": {"result": {"devices": [{**DEV, "usb_mode": "audio"}]}}})
    s = make_screen(fake)
    settle(s)
    assert "Sampler" in plain(s.render(100, 30))
    for tab in (cam.DEV_TAB_TRACE, cam.DEV_TAB_FILES):
        s.handle_key("tab")
        assert s.tab == tab
        assert "needs the CDC profile — switch in Connections" in plain(s.render(100, 30))
    assert fake.verb_calls("fs_roots") == []


def test_no_board_says_so_and_comes_back():
    fake = FakeHil({**BASE, "devices.list": {"result": {"devices": []}}})
    t = [100.0]
    s = make_screen(fake, t=t)
    settle(s)
    assert "No CrossPad connected" in plain(s.render(100, 30))
    fake.table.update(BASE)
    t[0] = 105.1
    settle(s)
    assert "Sampler" in plain(s.render(100, 30))


def test_a_silent_board_never_freezes_the_keys():
    t = [100.0]
    fake = FakeHil({**BASE, "cdc.verb:led_state": {"pending": True},
                    "cdc.verb:ui_state": {"pending": True},
                    "cdc.verb:enc_focus": {"pending": True}})
    s = make_screen(fake, t=t)
    settle(s)
    s.handle_key("right")
    assert fake.verb_calls("enc_rotate") == [{"delta": 1}]
    t[0] = 100.0 + cam._DeviceScreen.CALL_TIMEOUT_S + 1
    s.tick()
    assert "did not answer in time" in plain(s.render(100, 30))
    t[0] += 0.3
    s.tick()
    assert len(fake.verb_calls("led_state")) >= 2


def test_two_boards_the_first_is_named_on_every_call():
    fake = FakeHil({**BASE, "devices.list": {"result": {"devices": [DEV, {**DEV, "id": "dev_31ea"}]}}})
    s = make_screen(fake)
    settle(s)
    s.handle_key("z")
    op, args = fake.calls[-1]
    assert op == "cdc.verb" and args["device"] == DEV["id"]


def test_old_hil_without_hub_ops_is_quiet():
    fake = FakeHil({**BASE, "hub.status": {"error": {
        "code": "BAD_ARGS", "message": "unknown op 'hub.status'", "hint": "ops: …", "details": {}}}})
    s = make_screen(fake)
    settle(s)
    text = plain(s.render(100, 30))
    assert "hub: ?" in text and "unknown op" not in text


def test_dead_hil_says_how_to_upgrade():
    fake = FakeHil({**BASE, "hub.status": {"error": {
        "code": cam.HIL_EXITED, "message": "crosspad-hil stopped: unrecognized arguments: --client",
        "hint": None, "details": {}}}})
    s = make_screen(fake)
    settle(s)
    assert "pip install --upgrade" in plain(s.render(100, 30))


def test_every_tab_has_help_hints():
    s = make_screen(FakeHil(BASE))
    for tab in range(4):
        s.tab = tab
        assert "[Esc] back" in s.hints() or "[q] back" in s.hints()
