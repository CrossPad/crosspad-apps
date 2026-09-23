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
    assert by["Tools"]["ok"] is False and "ESP-IDF not found" in by["Tools"]["fix"]
    # Not being signed in to GitHub is a note, not a fault: reading apps needs no account.
    assert by["GitHub sign-in"]["ok"] is None and "only for publishing" in by["GitHub sign-in"]["fix"]
    assert by["Last update"]["detail"] == "never"


def test_whats_next_offline_outranks_the_tool_checks():
    # gh fails without a network, so "gh is not signed in" is the wrong thing
    # to tell someone whose wifi is off.
    n = cam.whats_next(ctx(offline=True, tools_missing=["gh is not signed in"]))
    assert n == {"line": "No connection — can't check for updates",
                 "action": "wrong", "estimate": None}


def test_whats_next_offline_does_not_hide_what_is_already_known():
    n = cam.whats_next(ctx(offline=True, updates=["Sampler"], estimate=240))
    assert n["action"] == "update" and n["line"] == "1 update waiting: Sampler"
    n = cam.whats_next(ctx(offline=True, mismatch=True, fw_rev="v1"))
    assert n["action"] == "update"


def test_wrong_rows_internet_row_says_which_way_it_is():
    facts = {"device": None, "board": {}, "idf_path": "/x", "gh_ok": True,
             "gh_user": "matixan", "python": "3.12.3", "usb_guard": None,
             "registry_age": 10, "last_update": None, "remembered_board": None}
    off = {r["title"]: r for r in cam.wrong_rows(dict(facts, offline=True))}["Internet"]
    assert off["ok"] is False and off["action"] == "refresh"
    assert off["detail"] == "no connection — updates and new apps need it"
    on = {r["title"]: r for r in cam.wrong_rows(dict(facts, offline=False))}["Internet"]
    assert on["ok"] is True and on["action"] is None and on["detail"] == "ok"


def test_looks_offline_tells_a_missing_network_from_a_missing_repo():
    assert cam.AppManager.looks_offline("fatal: could not resolve host: github.com")
    assert cam.AppManager.looks_offline("fatal: unable to access 'https://…': …")
    assert cam.AppManager.looks_offline("ssh: connect to host github.com: Network is unreachable")
    assert not cam.AppManager.looks_offline(
        "ERROR: Repository not found.\nfatal: Could not read from remote repository.")
    assert not cam.AppManager.looks_offline("")


def test_wrong_rows_tools_name_git_and_certificates():
    facts = {"device": None, "board": {}, "idf_path": "/x", "gh_ok": False, "gh_user": "",
             "git_ok": False, "python": "3.12.3", "usb_guard": None, "registry_age": 10,
             "last_update": None, "remembered_board": None, "cert_problem": True}
    by = {r["title"]: r for r in cam.wrong_rows(facts)}
    assert by["Tools"]["ok"] is False and "git is not installed" in by["Tools"]["detail"]
    assert by["HTTPS certificates"]["ok"] is False
    assert "Install Certificates.command" in by["HTTPS certificates"]["fix"]


def test_wrong_rows_on_pc_talk_about_the_simulator_not_a_board():
    facts = {"platform": "pc", "sim_built": None, "device": None, "board": {},
             "idf_path": "-", "gh_ok": True, "gh_user": "x", "git_ok": True,
             "python": "3.12.3", "usb_guard": None, "registry_age": 10,
             "last_update": None, "remembered_board": None}
    titles = [r["title"] for r in cam.wrong_rows(facts)]
    assert "Board found" not in titles and titles[0] == "Simulator"
    tools = {r["title"]: r for r in cam.wrong_rows(facts)}["Tools"]
    assert tools["ok"] is True and "ESP-IDF" not in tools["detail"]


def test_owner_repo_of_reads_every_github_spelling():
    assert cam.owner_repo_of("https://github.com/CrossPad/crosspad-sampler.git") == "CrossPad/crosspad-sampler"
    assert cam.owner_repo_of("git@github.com:CrossPad/crosspad-mixer") == "CrossPad/crosspad-mixer"
    assert cam.owner_repo_of("https://gitlab.com/x/y") is None
    assert cam.owner_repo_of("") is None


def test_change_summary_follows_the_rule_and_drops_commit_prefixes():
    avail = dict(AVAIL, release_log=["fix(sampler): kit selector remembers the last kit",
                                     "feat!: 16 levels"],
                 dev_log=["wip: half a looper"])
    assert cam.change_summary(status(), avail) == ["kit selector remembers the last kit", "16 levels"]
    assert cam.change_summary(status("branch", ref="master"), avail) == ["half a looper"]
    assert cam.change_summary(status("pinned", commit="x"), avail) == []
    assert cam.change_summary(status(), None) == []


def test_path_problems_catch_what_breaks_an_esp_idf_build():
    assert cam.path_problems("/home/a/cp", "esp-idf", False, None) == []
    assert "space" in cam.path_problems("/home/a/my projects/cp", "esp-idf", False, None)[0]
    assert "non-English" in cam.path_problems("/home/łukasz/cp", "esp-idf", False, None)[0]
    long_dir = "C:\\" + "x" * 120
    assert "long paths are off" in cam.path_problems(long_dir, "esp-idf", True, False)[0]
    assert cam.path_problems(long_dir, "esp-idf", True, True) == []
    assert cam.path_problems("/home/a/my projects", "pc", False, None) == []


def test_redact_blanks_secret_looking_keys_only():
    assert cam._redact({"board": "v2", "gh_token": "abc", "nested": [{"api_key": 1}]}) == \
        {"board": "v2", "gh_token": "***", "nested": [{"api_key": "***"}]}


def test_an_unfinished_update_is_offered_first_after_a_mismatch():
    n = cam.whats_next(ctx(unfinished="Build", updates=["Sampler"]))
    assert n == {"line": "The last update stopped at Build", "action": "resume", "estimate": None}
    assert cam.whats_next(ctx(unfinished="Build", mismatch=True, fw_rev="v1"))["action"] == "update"
