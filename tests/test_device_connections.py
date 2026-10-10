import crosspad_app_manager as cam
from tests.hil_fakes import BASE, DEV, FakeHil, make_screen, plain, settle

WIFI = {"state": "connected", "ssid": "Home", "rssi": -55, "ip": "10.42.0.254", "enabled": 1}
BLE_ON = {"supported": 1, "running": 1, "state": "advertising", "mode": "server", "peer": None}
TABLE = {**BASE, "cdc.verb:wifi_status": {"result": WIFI},
         "cdc.verb:wifi_list": {"result": ["Home", "Bench"]},
         "cdc.verb:ble_status": {"result": BLE_ON},
         "usbmode.set": {"result": {**DEV, "usb_mode": "audio"}}}


def conn(fake):
    s = make_screen(fake, tab=cam.DEV_TAB_CONN)
    settle(s)
    return s


def test_shows_usb_wifi_and_bluetooth():
    text = plain(conn(FakeHil(TABLE)).render(100, 30))
    assert "CDC" in text and "[u] switch to USB audio" in text
    assert "asks on its screen" in text
    assert "connected · Home · 10.42.0.254 · -55 dBm" in text
    assert "Bench" in text and "on · server" in text


def test_usb_switch_asks_then_switches(monkeypatch):
    fake = FakeHil(TABLE)
    s = conn(fake)
    monkeypatch.setattr(cam, "_confirm", lambda prompt: True)
    s.handle_key("u")
    assert ("usbmode.set", {"holder": "cp-tools", "mode": "audio"}) in fake.calls
    assert "Allow" in plain(s.render(100, 30))
    s.tick()
    assert s.dev["usb_mode"] == "audio" and "USB audio now" in plain(s.render(100, 30))


def test_usb_switch_back_works_in_the_audio_profile(monkeypatch):
    fake = FakeHil({**TABLE, "devices.list": {"result": {"devices": [{**DEV, "usb_mode": "audio"}]}}})
    s = conn(fake)
    monkeypatch.setattr(cam, "_confirm", lambda prompt: True)
    s.handle_key("u")
    assert ("usbmode.set", {"holder": "cp-tools", "mode": "default"}) in fake.calls


def test_add_and_forget_a_network(monkeypatch):
    fake = FakeHil(TABLE)
    s = conn(fake)
    answers = iter(["Studio", "longenough"])
    monkeypatch.setattr(cam, "_text_input", lambda prompt, default="": next(answers))
    s.handle_key("n")
    assert fake.verb_calls("wifi_set") == [{"ssid": "Studio", "password": "longenough"}]
    monkeypatch.setattr(cam, "_confirm", lambda prompt: True)
    s.handle_key("down")
    s.handle_key("x")
    assert fake.verb_calls("wifi_forget") == [{"ssid": "Bench"}]


def test_a_short_password_is_refused_here(monkeypatch):
    fake = FakeHil(TABLE)
    s = conn(fake)
    answers = iter(["Studio", "short"])
    monkeypatch.setattr(cam, "_text_input", lambda prompt, default="": next(answers))
    s.handle_key("n")
    assert fake.verb_calls("wifi_set") == []
    assert "at least 8 characters" in plain(s.render(100, 30))


def test_bluetooth_toggles():
    fake = FakeHil(TABLE)
    s = conn(fake)
    s.handle_key("b")
    assert fake.verb_calls("ble_enable") == [{"on": False}]


def test_text_helpers():
    assert cam.wifi_text(None) == "-"
    assert cam.wifi_text({"state": "off", "ssid": None, "enabled": 0}) == "off · off in settings"
    assert cam.ble_text({"supported": 0}) == "not on this firmware"
    assert cam.ble_text({"supported": 1, "running": 0}) == "off"
