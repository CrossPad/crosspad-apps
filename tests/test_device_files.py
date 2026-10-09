import crosspad_app_manager as cam
from tests.hil_fakes import BASE, FakeHil, make_screen, plain, settle

ROOTS = {"roots": {"/sdcard": {"total": 32_000_000_000, "used": 1_200_000_000},
                   "/assets": {"total": 4_000_000, "used": 3_100_000},
                   "/spiflash": {"total": None, "used": None}}}
LISTING = {"path": "/sdcard", "entries": [{"name": "a.wav", "dir": False, "size": 1234},
                                          {"name": "kits", "dir": True, "size": 0}]}
IDLE = {"busy": False, "op": None, "ok": None, "err": None, "path": None}
TABLE = {**BASE, "cdc.verb:fs_roots": {"result": ROOTS}, "cdc.verb:fs_list": {"result": LISTING},
         "cdc.verb:settings_status": {"result": IDLE},
         "fs.pull": {"result": {"bytes": 1234, "seconds": 0.5}},
         "fs.push": {"result": {"bytes": 10, "seconds": 0.1}}}


def open_sdcard(fake, tmp_path, t=None):
    s = make_screen(fake, tab=cam.DEV_TAB_FILES, project_dir=tmp_path, t=t)
    settle(s)
    s.handle_key("enter")                   # /sdcard is the first mount
    s.tick()
    return s


def test_rows_folders_first_and_mounts_in_board_order():
    assert cam.fs_entries(LISTING) == [{"name": "kits", "dir": True, "size": 0},
                                       {"name": "a.wav", "dir": False, "size": 1234}]
    assert [r["mount"] for r in cam.fs_root_rows(ROOTS)] == ["/sdcard", "/assets", "/spiflash"]
    assert cam.fs_root_rows(ROOTS)[2] == {"mount": "/spiflash", "total": None, "used": None}


def test_mounts_then_a_folder_folders_first(tmp_path):
    fake = FakeHil(TABLE)
    s = make_screen(fake, tab=cam.DEV_TAB_FILES, project_dir=tmp_path)
    settle(s)
    text = plain(s.render(100, 30))
    assert "/sdcard" in text and "/assets" in text and "not mounted" in text
    s.handle_key("enter")
    s.tick()
    assert fake.verb_calls("fs_list") == [{"path": "/sdcard"}]
    text = plain(s.render(100, 30))
    assert text.index("kits/") < text.index("a.wav")
    s.handle_key("left")
    s.tick()
    assert s.cwd is None and len(fake.verb_calls("fs_roots")) == 2


def test_pull_saves_under_the_project(tmp_path, monkeypatch):
    fake = FakeHil(TABLE)
    s = open_sdcard(fake, tmp_path)
    monkeypatch.setattr(cam, "_text_input", lambda prompt, default="": default)
    s.handle_key("down")                    # a.wav
    s.handle_key("p")
    local = str(tmp_path / ".crosspad" / "files" / "a.wav")
    assert ("fs.pull", {"holder": "cp-tools", "remote": "/sdcard/a.wav", "local": local}) in fake.calls
    assert (tmp_path / ".crosspad" / "files").is_dir()
    s.tick()
    assert s.transfer is None and f"Saved {local}" in plain(s.render(100, 30))


def test_keys_wait_while_a_transfer_runs(tmp_path, monkeypatch):
    fake = FakeHil({**TABLE, "fs.pull": {"pending": True}})
    s = open_sdcard(fake, tmp_path)
    monkeypatch.setattr(cam, "_text_input", lambda prompt, default="": default)
    s.handle_key("down")
    s.handle_key("p")
    s.tick()
    assert "Pulling a.wav" in plain(s.render(100, 30))
    s.handle_key("x")
    assert fake.verb_calls("fs_delete") == []


def test_a_folder_is_not_pulled(tmp_path):
    fake = FakeHil(TABLE)
    s = open_sdcard(fake, tmp_path)
    s.handle_key("p")                       # kits/
    assert "folders are not pulled" in plain(s.render(100, 30))
    assert not any(op == "fs.pull" for op, _a in fake.calls)


def test_push_sends_a_file_into_this_folder(tmp_path, monkeypatch):
    src = tmp_path / "kick.wav"
    src.write_bytes(b"RIFF")
    fake = FakeHil(TABLE)
    s = open_sdcard(fake, tmp_path)
    monkeypatch.setattr(cam, "_text_input", lambda prompt, default="": str(src))
    s.handle_key("u")
    assert ("fs.push", {"holder": "cp-tools", "local": str(src),
                        "remote": "/sdcard/kick.wav"}) in fake.calls


def test_push_of_a_missing_file_says_so(tmp_path, monkeypatch):
    fake = FakeHil(TABLE)
    s = open_sdcard(fake, tmp_path)
    monkeypatch.setattr(cam, "_text_input", lambda prompt, default="": str(tmp_path / "nope"))
    s.handle_key("u")
    assert "No such file" in plain(s.render(100, 30))


def test_new_folder_and_delete(tmp_path, monkeypatch):
    fake = FakeHil(TABLE)
    s = open_sdcard(fake, tmp_path)
    monkeypatch.setattr(cam, "_text_input", lambda prompt, default="": "loops")
    monkeypatch.setattr(cam, "_confirm", lambda prompt: True)
    s.handle_key("n")
    s.handle_key("down")
    s.handle_key("x")
    assert fake.verb_calls("fs_mkdir") == [{"path": "/sdcard/loops"}]
    assert fake.verb_calls("fs_delete") == [{"path": "/sdcard/a.wav"}]


def test_settings_save_is_followed_until_done(tmp_path):
    t = [100.0]
    fake = FakeHil({**TABLE, "cdc.verb:settings_export": {"result": {
        "started": True, "path": "/sdcard/crosspad-settings.json"}}})
    s = make_screen(fake, tab=cam.DEV_TAB_FILES, project_dir=tmp_path, t=t)
    settle(s)
    fake.table["cdc.verb:settings_status"] = {"result": {"busy": True, "op": "export", "ok": None,
                                                          "err": None, "path": None}}
    s.handle_key("e")
    settle(s, 2)
    assert "save running" in plain(s.render(100, 30))
    fake.table["cdc.verb:settings_status"] = {"result": {
        "busy": False, "op": "export", "ok": True, "err": None,
        "path": "/sdcard/crosspad-settings.json"}}
    t[0] += cam.SETTINGS_POLL_S + 0.1
    s.tick()
    assert "last save: ok" in plain(s.render(100, 30))


def test_settings_load_asks_first(tmp_path, monkeypatch):
    fake = FakeHil(TABLE)
    s = make_screen(fake, tab=cam.DEV_TAB_FILES, project_dir=tmp_path)
    settle(s)
    monkeypatch.setattr(cam, "_confirm", lambda prompt: False)
    s.handle_key("i")
    assert fake.verb_calls("settings_import") == []
    monkeypatch.setattr(cam, "_confirm", lambda prompt: True)
    s.handle_key("i")
    assert fake.verb_calls("settings_import") == [{"path": "/sdcard/crosspad-settings.json"}]


def test_no_cdc_error_gives_the_audio_notice():
    fake = FakeHil({**TABLE, "cdc.verb:fs_roots": {"error": {
        "code": "NO_CDC_IN_AUDIO_MODE", "message": "no CDC", "hint": None, "details": {}}}})
    s = make_screen(fake, tab=cam.DEV_TAB_FILES)
    settle(s)
    assert "needs the CDC profile — switch in Connections" in plain(s.render(100, 30))


def test_settings_text():
    assert cam.settings_text(None) == "-"
    assert cam.settings_text({"busy": False, "op": "import", "ok": False, "err": "parse"}) == \
        "last load failed: parse"
