import crosspad_app_manager as cam


def test_viewport_keeps_cursor_visible():
    assert cam._viewport(0, 3, 10) == (0, 3)
    assert cam._viewport(0, 30, 10) == (0, 10)
    assert cam._viewport(9, 30, 10) == (0, 10)
    assert cam._viewport(10, 30, 10) == (1, 11)
    assert cam._viewport(29, 30, 10) == (20, 30)
    assert cam._viewport(5, 30, 0) == (5, 6)


def test_glyphs_have_ascii_fallbacks():
    for name, val in cam.G.items():
        assert name in cam.G_ASCII, name
        assert cam.G_ASCII[name].isascii()


def test_use_ascii_off_on_posix(monkeypatch):
    monkeypatch.setattr(cam.sys, "platform", "linux")
    assert cam._use_ascii() is False


def test_use_ascii_on_windows_without_utf8(monkeypatch):
    monkeypatch.setattr(cam.sys, "platform", "win32")
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.setattr(cam, "_console_utf8", lambda: False)
    assert cam._use_ascii() is True
    monkeypatch.setenv("WT_SESSION", "1")
    assert cam._use_ascii() is False


def test_clicks_land_on_the_bracketed_key_they_hit(monkeypatch):
    monkeypatch.setattr(cam, "MOUSE", True)
    monkeypatch.setattr(cam.sys, "stdout", __import__("io").StringIO())
    cam._clear()
    cam._w("\n  \x1b[1;36mCrossPad\x1b[0m\n")
    cam._w(" \x1b[1;36m[1]\x1b[0m Update my CrossPad     \x1b[1;36m[2]\x1b[0m Add or remove apps\n")
    cam._w("  [Enter] do it   [q] back\n")
    row = 4 if cam.PLAIN else 3
    assert cam._hotspot_key(2, row) == "1" and cam._hotspot_key(4, row) == "1"
    assert cam._hotspot_key(30, row) == "2"
    assert cam._hotspot_key(10, row) == ""
    assert cam._hotspot_key(4, row + 1) == "enter" and cam._hotspot_key(19, row + 1) == "q"
