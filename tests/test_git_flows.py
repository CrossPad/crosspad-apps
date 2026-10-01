"""Go back and repair against real git repositories (no network, no terminal)."""
import json
import subprocess

import pytest

import crosspad_app_manager as cam


def git(cwd, *args):
    return subprocess.run(["git", "-c", "protocol.file.allow=always", "-c", "user.email=t@t",
                           "-c", "user.name=t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")
    app = tmp_path / "crosspad-sampler"
    app.mkdir()
    git(app, "init", "-q", "-b", "main")
    (app / "a.txt").write_text("1")
    git(app, "add", ".")
    git(app, "commit", "-qm", "one")
    first = git(app, "rev-parse", "HEAD")
    (app / "a.txt").write_text("2")
    git(app, "commit", "-qam", "two")
    second = git(app, "rev-parse", "HEAD")

    proj = tmp_path / "proj"
    proj.mkdir()
    git(proj, "init", "-q", "-b", "main")
    git(proj, "submodule", "add", "-q", str(app), "components/crosspad-sampler")
    git(proj, "commit", "-qm", "sub")
    (proj / "apps.json").write_text(json.dumps({"installed": {"sampler": {"ref": "main"}}}))
    (proj / "app-registry.json").write_text(json.dumps({"apps": {}}))
    mgr = cam.AppManager(str(proj), cam.PlatformConfig(platform="pc", lib_dir="components"))
    return mgr, proj, first, second


def test_go_back_checks_out_the_previous_commit_and_keeps_it(project):
    mgr, proj, first, second = project
    mgr.save_last_update({"ok": True, "previous": {"sampler": first},
                          "after": {"sampler": second}})
    assert mgr.rollback_plan() == {"sampler": first}
    assert mgr.roll_back() == ["sampler"]
    assert git(proj / "components/crosspad-sampler", "rev-parse", "HEAD") == first
    assert mgr.app_policy("sampler") == {"track": "pinned", "commit": first}


def test_repair_brings_back_a_folder_whose_git_data_is_gone(project):
    mgr, proj, first, second = project
    import shutil
    folder = proj / "components/crosspad-sampler"
    (folder / ".git").unlink()                        # a submodule's .git is a file
    assert mgr.app_status("sampler")["git"]["broken"]
    (folder / "mine.txt").write_text("work")
    ok, msg = mgr.repair_app("sampler")
    assert ok, msg
    assert mgr.app_status("sampler")["git"].get("broken") is None
    saved = list(mgr.backup_dir("sampler").glob("*/folder.tgz"))
    assert saved, "the folder's files were not kept"
    shutil.rmtree(folder)
    ok, msg = mgr.repair_app("sampler", fresh=True)
    assert ok, msg
    assert (folder / "a.txt").read_text() == "2"


def test_a_detached_app_that_follows_development_gets_onto_its_branch(project):
    # What every fresh clone looks like: the submodule on the recorded commit,
    # no branch. 'Follows development' must still update it.
    mgr, proj, first, second = project
    sub = proj / "components/crosspad-sampler"
    git(sub, "checkout", "-q", first)
    mgr.set_app_policy("sampler", "branch", ref="main")
    mgr.update(app_name="sampler")
    assert git(sub, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git(sub, "rev-parse", "HEAD") == second


@pytest.fixture
def behind(tmp_path, monkeypatch):
    """A project clone two commits behind origin, with an app submodule."""
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")
    app = tmp_path / "crosspad-sampler"
    app.mkdir()
    git(app, "init", "-q", "-b", "main")
    (app / "a.txt").write_text("1")
    git(app, "add", ".")
    git(app, "commit", "-qm", "one")
    up = tmp_path / "up"
    up.mkdir()
    git(up, "init", "-q", "-b", "main")
    (up / "main.cpp").write_text("a\nb\nc\nd\ne\n")
    (up / "other.cpp").write_text("x\n")
    git(up, "add", ".")
    git(up, "submodule", "add", "-q", str(app), "components/crosspad-sampler")
    git(up, "commit", "-qm", "base")
    proj = tmp_path / "proj"
    git(tmp_path, "clone", "-q", "--recurse-submodules", str(up), "proj")
    (app / "a.txt").write_text("2")
    git(app, "commit", "-qam", "two")
    git(up / "components/crosspad-sampler", "pull", "-q", "origin", "main")
    (up / "main.cpp").write_text("A\nb\nc\nd\ne\n")
    git(up, "commit", "-qam", "upstream edits main.cpp and moves the app")
    (up / "new.cpp").write_text("n\n")
    git(up, "add", ".")
    git(up, "commit", "-qm", "upstream adds new.cpp")
    mgr = cam.AppManager(str(proj), cam.PlatformConfig(platform="idf", lib_dir="components"))
    return mgr, proj, up


def test_project_update_fast_forwards_a_clean_project(behind):
    mgr, proj, up = behind
    assert mgr.update_project() == ("updated", "2 new commits")
    assert git(proj, "rev-parse", "HEAD") == git(up, "rev-parse", "HEAD")
    assert mgr.update_project() == ("current", "up to date")


def test_project_update_carries_edits_and_moved_app_pointers(behind):
    mgr, proj, up = behind
    (proj / "main.cpp").write_text("a\nb\nc\nd\nE\n")      # same file, other line
    (proj / "other.cpp").write_text("mine\n")                 # file upstream never touched
    (proj / "untracked.cpp").write_text("u\n")
    sub = proj / "components/crosspad-sampler"
    git(sub, "pull", "-q", "origin", "main")                   # what update() does to an app
    git(proj, "add", "components/crosspad-sampler")
    state, _ = mgr.update_project()
    assert state == "updated"
    assert git(proj, "rev-parse", "HEAD") == git(up, "rev-parse", "HEAD")
    assert (proj / "main.cpp").read_text() == "A\nb\nc\nd\nE\n"
    assert (proj / "other.cpp").read_text() == "mine\n"
    assert (proj / "untracked.cpp").exists()
    assert git(proj, "stash", "list") == ""


def test_project_update_leaves_a_clashing_edit_alone(behind):
    mgr, proj, up = behind
    head = git(proj, "rev-parse", "HEAD")
    (proj / "main.cpp").write_text("mine\nb\nc\nd\ne\n")
    state, msg = mgr.update_project()
    assert state == "clash" and "main.cpp" in msg
    assert git(proj, "rev-parse", "HEAD") == head
    assert (proj / "main.cpp").read_text() == "mine\nb\nc\nd\ne\n"


def test_project_update_never_merges_over_local_commits(behind):
    mgr, proj, up = behind
    (proj / "other.cpp").write_text("mine\n")
    git(proj, "commit", "-qam", "local")
    head = git(proj, "rev-parse", "HEAD")
    assert mgr.update_project()[0] == "local-commits"
    assert git(proj, "rev-parse", "HEAD") == head
