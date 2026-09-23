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


def test_release_target_prefers_tag_then_branch():
    assert cam._release_target(TAGS, "master") == "v0.3.0"
    assert cam._release_target([("nightly", "")], "master") == "origin/master"


def test_registry_policy_after_fresh_install_marks_release_current():
    """Regression for _install_flow: installing from Add-or-remove-apps
    always means Latest release (spec §4), so the policy left behind must
    be {"track": "registry"} — not track=branch with the install ref (a
    release tag), which the version screen would then show as Latest
    development instead."""
    rows = cam.version_rows({"track": "registry"}, "main", "abc1234", "v0.3.0",
                            [("v0.3.0", "2026-09-14")], "abc1234", 0)
    assert rows[0].kind == "release" and rows[0].current
    assert not any(r.kind == "development" and r.current for r in rows)


def test_version_satisfies_the_spec_forms_the_registry_uses():
    assert cam.version_satisfies((1, 20, 0), ">=0.3.0")
    assert not cam.version_satisfies((0, 2, 9), ">=0.3.0")
    assert cam.version_satisfies((1, 4, 2), "^1.4") and not cam.version_satisfies((2, 0, 0), "^1.4")
    assert cam.version_satisfies((1, 4, 9), "~1.4.1") and not cam.version_satisfies((1, 5, 0), "~1.4.1")
    assert cam.version_satisfies((1, 2, 3), "1.2.3") and cam.version_satisfies((9, 9, 9), "*")
    assert cam.version_satisfies(None, ">=5.0.0")          # unknown is not a refusal
    assert not cam.version_satisfies((1, 2, 0), ">=1.0.0, <1.2.0")


def test_unmet_requirements_name_the_component_and_both_versions():
    have = {"crosspad-core": (1, 20, 0), "crosspad-gui": (1, 11, 1)}
    assert cam.unmet_requirements({"crosspad-core": ">=0.3.0", "crosspad-gui": ">=0.2.1"}, have) == []
    assert cam.unmet_requirements({"crosspad-core": ">=2.0.0"}, have) == \
        ["needs core >=2.0.0, this project has 1.20.0"]
    assert cam.unmet_requirements(["crosspad-core"], have) == []
    assert cam.unmet_requirements(None, have) == []


def test_app_row_broken_folder_is_its_own_state():
    st = {"policy": {"track": "registry"}, "blocking": [],
          "git": {"exists": True, "head": None, "broken": "no git data in the folder"}}
    assert cam.app_row(st, None, True)["state"] == "broken"


def test_catalog_problems_say_what_an_author_must_fix():
    meta = {"id": "fishtank", "name": "Fish Tank", "version": "0.1.0",
            "description": "fish", "platforms": ["esp-idf"]}
    assert cam.catalog_problems(meta, "PUBLIC", "me/crosspad-fishtank", []) == []
    assert "no GitHub repository" in cam.catalog_problems(meta, None, None, [])[0]
    assert "private" in cam.catalog_problems(meta, "PRIVATE", "me/x", [])[0]
    assert cam.catalog_problems(dict(meta, version="soon"), "PUBLIC", "me/x", []) == \
        ['version "soon" is not like 1.2.3']
    assert 'no "platforms"' in cam.catalog_problems(dict(meta, platforms=[]), "PUBLIC", "me/x", [])[0]
    assert "already" in cam.catalog_problems(meta, "PUBLIC", "Me/X", ["me/x"])[0]
    assert "missing" in cam.catalog_problems(None, "PUBLIC", "me/x", [])[0]
