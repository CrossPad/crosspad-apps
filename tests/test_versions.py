import crosspad_app_manager as cam

TAGS = [("v0.3.0", "2026-09-14"), ("v0.2.1", "2026-08-18"), ("v0.2.0", "2026-08-01")]


def test_follow_rule_maps_track_modes():
    assert cam.follow_rule({"track": "registry"}) == ("release", "")
    assert cam.follow_rule({"track": "branch", "ref": "master"}) == ("development", "master")
    assert cam.follow_rule({"track": "pinned", "commit": "8e21e0f"}) == ("version", "8e21e0f")
    assert cam.follow_rule({"track": "local"}) == ("own", "")
    assert cam.follow_rule({}) == ("release", "")


def test_parse_tag_lines_keeps_order_and_dates():
    text = "v0.3.0 2026-09-14\nv0.2.1 2026-08-18\n\nnot-a-date-line\n"
    assert cam.parse_tag_lines(text) == [("v0.3.0", "2026-09-14"), ("v0.2.1", "2026-08-18"),
                                         ("not-a-date-line", "")]


def test_newest_release_skips_non_semver_tags():
    assert cam.newest_release([("nightly", "2026-09-15")] + TAGS) == "v0.3.0"
    assert cam.newest_release([("nightly", "")]) is None
    assert cam.newest_release([]) is None


def test_version_rows_release_current_and_installed_marks():
    rows = cam.version_rows({"track": "registry"}, "master", "b048ab8", "v0.2.1",
                            TAGS, "4ac6d69", 17)
    kinds = [r.kind for r in rows]
    assert kinds == ["release", "development", "version", "version", "version", "other"]
    assert rows[0].current and rows[0].recommended and rows[0].target == "v0.3.0"
    assert rows[0].detail == "0.3.0    auto-update"
    assert rows[1].detail == "master   4ac6d69, 17 commits newer"
    assert rows[3].label == "0.2.1" and rows[3].installed and rows[3].detail == "2026-08-18"
    assert not rows[3].current


def test_version_rows_pinned_marks_the_concrete_row_current():
    rows = cam.version_rows({"track": "pinned", "commit": "8e21e0f"}, "master", "8e21e0f", None,
                            TAGS, "4ac6d69", 17)
    current = [r for r in rows if r.current]
    assert len(current) == 1 and current[0].kind == "other"
    assert current[0].label == "8e21e0f"
    assert current[0].installed


def test_version_rows_without_tags_says_so():
    rows = cam.version_rows({"track": "registry"}, "main", "abc1234", None, [], "abc1234", 0)
    assert rows[0].detail == "no releases yet, uses main"
    assert rows[0].target == "main"
    assert rows[1].detail == "main     abc1234, up to date"
