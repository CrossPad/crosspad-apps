import crosspad_app_manager as cam


def status(track="registry", ref=None, commit=None, blocking=(), head="b048ab8", exists=True):
    policy = {"track": track}
    if ref:
        policy["ref"] = ref
    if commit:
        policy["commit"] = commit
    return {"app": "sampler", "policy": policy, "blocking": list(blocking),
            "git": {"exists": exists, "head": head}}


AVAIL = {"tags": [["v0.3.0", "2026-09-14"], ["v0.2.1", "2026-08-18"]], "default_branch": "master",
         "dev_head": "4ac6d69", "dev_behind": 17, "release_behind": 5, "installed_tag": "v0.2.1"}


def test_app_row_release_with_newer_tag_is_update():
    row = cam.app_row(status(), AVAIL, True)
    assert row == {"state": "update", "installed": "0.2.1", "available": "0.3.0"}


def test_app_row_release_up_to_date():
    row = cam.app_row(status(), dict(AVAIL, release_behind=0, installed_tag="v0.3.0"), True)
    assert row["state"] == "current" and row["installed"] == "0.3.0"


def test_app_row_development_uses_behind_count():
    row = cam.app_row(status("branch", ref="master"), AVAIL, True)
    assert row == {"state": "update", "installed": "0.2.1", "available": "master 4ac6d69"}
    assert cam.app_row(status("branch", ref="master"), dict(AVAIL, dev_behind=0), True)["state"] == "current"


def test_app_row_pinned_never_updates_and_shows_sha_without_tag():
    row = cam.app_row(status("pinned", commit="8e21e0f", head="8e21e0f"),
                      dict(AVAIL, installed_tag=None), True)
    assert row == {"state": "current", "installed": "8e21e0f", "available": ""}


def test_app_row_local_work_and_own_copy_and_missing():
    assert cam.app_row(status(blocking=["dirty"]), AVAIL, True)["state"] == "changes"
    assert cam.app_row(status("local"), None, False)["state"] == "own"
    assert cam.app_row(status(), None, False)["state"] == "own"
    assert cam.app_row(status(exists=False), AVAIL, True)["state"] == "missing"


def test_app_row_without_available_record_is_current():
    assert cam.app_row(status(), None, True)["state"] == "current"


def ctx(**kw):
    base = {"board_rev": "v2", "fw_rev": "v2", "mismatch": False, "updates": [],
            "apps_changed": False, "components_moved": False, "tools_missing": [],
            "estimate": None}
    base.update(kw)
    return base


def test_whats_next_priority():
    n = cam.whats_next(ctx(mismatch=True, fw_rev="v1", updates=["Sampler"]))
    assert n["action"] == "update" and n["line"] == "The board runs v1 firmware on a v2 board"

    n = cam.whats_next(ctx(updates=["Sampler", "Mixer", "Instructions"], estimate=240))
    assert n["line"] == "3 updates waiting: Sampler, Mixer, Instructions"
    assert n["action"] == "update" and n["estimate"] == 240

    n = cam.whats_next(ctx(updates=["Sampler"]))
    assert n["line"] == "1 update waiting: Sampler"

    n = cam.whats_next(ctx(apps_changed=True))
    assert n["line"] == "Apps changed — put them on the board" and n["action"] == "update"

    n = cam.whats_next(ctx(components_moved=True))
    assert n["action"] == "update"

    n = cam.whats_next(ctx(tools_missing=["gh is not signed in"]))
    assert n["line"] == "Set up: gh is not signed in" and n["action"] == "wrong"

    n = cam.whats_next(ctx())
    assert n["line"] == "Everything is up to date" and n["action"] == "none"


def test_wrong_rows_without_board_and_with_guard_on():
    rows = cam.wrong_rows({"device": None, "board": {"rev": "v2", "source": "memory"},
                           "idf_path": "/x", "gh_ok": True, "gh_user": "matixan",
                           "python": "3.12.3", "usb_guard": None, "registry_age": 200000,
                           "last_update": {"finished": "2026-09-14T21:14:00+00:00", "ok": True},
                           "remembered_board": "v2"})
    titles = [r["title"] for r in rows]
    assert titles[0] == "Board found" and rows[0]["ok"] is False
    assert "plug it in over USB" in rows[0]["detail"]
    reg = next(r for r in rows if r["title"] == "Registry")
    assert reg["ok"] is None and reg["action"] == "refresh"
    assert next(r for r in rows if r["title"] == "Tools")["ok"] is True


def test_wrong_rows_usb_guard_and_mismatch():
    rows = cam.wrong_rows({"device": {"id": "dev_31ea", "board_rev": "v2", "fw_rev": "v1",
                                      "usb_mode": "default"},
                           "board": {"rev": "v2", "source": "device", "fw_rev": "v1", "mismatch": True},
                           "idf_path": "", "gh_ok": False, "gh_user": "", "python": "3.12.3",
                           "usb_guard": "1", "registry_age": 10, "last_update": None,
                           "remembered_board": None})
    by = {r["title"]: r for r in rows}
    assert by["Firmware"]["ok"] is False and by["Firmware"]["action"] == "update"
    assert by["USB serial guard"]["ok"] is False and by["USB serial guard"]["action"] == "usb_guard_off"
    assert by["Tools"]["ok"] is False and "gh auth login" in by["Tools"]["fix"]
    assert by["Last update"]["detail"] == "never"
