import crosspad_app_manager as cam

LAST = {"finished": "2026-09-14T21:14:00+00:00", "ok": True,
        "installed_set": ["sampler", "mixer"], "build_rev": "v2",
        "steps": [{"name": "download", "ok": True, "seconds": 12},
                  {"name": "components", "ok": True, "seconds": 3},
                  {"name": "build", "ok": True, "seconds": 190},
                  {"name": "flash", "ok": True, "seconds": 30},
                  {"name": "check", "ok": True, "seconds": 5}]}


def test_plan_fullclean_when_app_set_changed_or_no_record():
    assert cam.plan_update(None, ["sampler"], True)["fullclean"] is True
    assert cam.plan_update(LAST, ["sampler", "mixer"], True)["fullclean"] is False
    assert cam.plan_update(LAST, ["sampler", "mixer", "fishtank"], True)["fullclean"] is True


def test_plan_steps_and_estimate():
    p = cam.plan_update(LAST, ["sampler", "mixer"], True)
    assert p["steps"] == ["download", "components", "build", "flash", "check"]
    assert p["estimate"] == 240
    p = cam.plan_update(LAST, ["sampler", "mixer"], False)
    assert p["steps"] == ["download", "components", "build"]
    assert p["estimate"] == 205
    assert cam.plan_update(None, [], True)["estimate"] is None


def test_estimate_ignores_a_failed_last_run():
    assert cam.plan_update(dict(LAST, ok=False), ["sampler", "mixer"], True)["estimate"] is None


def test_parse_ninja_progress():
    assert cam.parse_ninja_progress("[1187/1952] Building CXX object esp-idf/main/x.obj") == (1187, 1952)
    assert cam.parse_ninja_progress("-- Configuring done") is None


def test_build_failure_where_names_the_app():
    tail = ["[12/30] Building CXX object",
            "/home/u/platform-idf/components/crosspad-sampler/src/a.cpp:12:5: error: x",
            "ninja: build stopped"]
    dirs = {"Sampler": "components/crosspad-sampler", "Mixer": "components/crosspad-mixer"}
    assert cam.build_failure_where(tail, dirs) == "Sampler"
    assert cam.build_failure_where(["main/main.cpp:1:1: error: y"], dirs) == "the firmware"


def test_error_lines_say_what_to_do():
    assert cam.error_line("download", "offline") == \
        "Can't reach GitHub — check your connection, then [r] retry"
    assert cam.error_line("build", "failed", "Sampler") == \
        "Build failed in Sampler → [c] show the error   [3] Something's wrong"
    assert cam.error_line("flash", "no-answer") == \
        "The board isn't answering → [r] retry   [3] Something's wrong"
    assert cam.error_line("check", "mismatch", "Sampler") == \
        "The board still runs the old Sampler → [r] flash again"
    assert cam.error_line("build", "no-tools") == \
        "Build tools are missing → [3] Something's wrong"
    assert cam.error_line("components", "failed") == \
        "Couldn't fetch firmware components → [r] retry"


def test_release_image_only_for_the_exact_checkout():
    comps = {"components/crosspad-core": "a" * 40, "components/crosspad-sampler": "b" * 40}
    heads = {"components/crosspad-core": "a" * 40, "components/crosspad-sampler": "b" * 40}
    assert cam.checkout_matches_release(comps, heads, [], []) == (True, "")
    ok, why = cam.checkout_matches_release(comps, dict(heads, **{"components/crosspad-sampler": "c" * 40}), [], [])
    assert not ok and why == "crosspad-sampler is on another version"
    assert cam.checkout_matches_release(comps, heads, ["components/crosspad-core"], [])[0] is False
    assert cam.checkout_matches_release(comps, heads, [], ["CP_X=1"])[1] == "feature flags differ from the defaults"
    assert "not in this project" in cam.checkout_matches_release(comps, {}, [], [])[1]


def test_release_names_and_checksums():
    n = cam.release_asset_names("v1.0.2", "v2")
    assert n["image"] == "CrossPad-v1.0.2-v2.bin" and n["components"] == "CrossPad-v1.0.2-components.json"
    sums = cam.parse_sha256sums("%s  CrossPad-v1.0.2-v2.bin\n%s *SHA256SUMS.txt\njunk\n" % ("A" * 64, "b" * 64))
    assert sums == {"CrossPad-v1.0.2-v2.bin": "a" * 64, "SHA256SUMS.txt": "b" * 64}
