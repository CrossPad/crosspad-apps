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
