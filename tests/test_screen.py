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
