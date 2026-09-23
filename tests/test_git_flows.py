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
