"""Rendering the app template, wherever the template was fetched to."""
import crosspad_app_manager as cam


def _manager(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    return cam.AppManager(str(proj), cam.PlatformConfig(platform="idf", lib_dir="components")), proj


def _template(root):
    (root / "src").mkdir(parents=True)
    (root / "src" / "__APP_ID__.cpp.tmpl").write_text("// __APP_NAME__\n")
    (root / "CMakeLists.txt").write_text("# __APP_ID__\n")
    (root / ".crosspad").mkdir()                      # working data that landed in the template
    (root / ".crosspad" / "last-update.log").write_text("x")
    (root / "apps.json").write_text("{}")


def test_a_template_cached_under_the_projects_crosspad_folder_renders(tmp_path, monkeypatch):
    mgr, proj = _manager(tmp_path)
    cache = proj / cam.WORK_ROOT / "template"          # where a platform wrapper fetches it
    _template(cache)
    monkeypatch.setattr(mgr, "_template_dir", lambda: cache)
    dest = tmp_path / "out"
    written = mgr._render_template(dest, {"__APP_ID__": "fishtank", "__APP_NAME__": "Fish Tank"})
    assert written == 2
    assert (dest / "src" / "fishtank.cpp").read_text() == "// Fish Tank\n"
    assert (dest / "CMakeLists.txt").read_text() == "# fishtank\n"
    assert not (dest / ".crosspad").exists()
    assert not (dest / "apps.json").exists()


# -- fetching the template in a platform project ------------------------------
#
# A platform wrapper keeps only the manager core in tools/, with no template/
# beside it, so `new` downloads crosspad-apps' template/ into .crosspad/.

import base64
import io
import os
import subprocess
import tarfile
import time


def _platform_layout(tmp_path, monkeypatch):
    """The manager as platform-idf / crosspad-pc carry it: tools/, no template/."""
    mgr, proj = _manager(tmp_path)
    tools = proj / "tools"
    tools.mkdir()
    monkeypatch.setattr(cam, "__file__", str(tools / "crosspad_app_manager.py"))
    return mgr, proj / cam.WORK_ROOT / "template"


def _tarball(entries):
    """A codeload-style tarball: every path under one 'crosspad-apps-main/' folder."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(f"crosspad-apps-main/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _no_gh(*args, **kwargs):
    raise AssertionError(f"gh must not be needed: {args[0] if args else kwargs}")


def test_the_template_downloads_without_a_github_account(tmp_path, monkeypatch):
    mgr, cache = _platform_layout(tmp_path, monkeypatch)
    urls = []

    def fake_get(url, timeout=None):
        urls.append(url)
        return _tarball({
            "template/src/__APP_CLASS__App.cpp.tmpl": b"// app\n",
            "template/CMakeLists.txt.tmpl": b"# __APP_ID__\n",
            "template/../escape.txt": b"x",           # must not climb out
            "registry.json": b"{}",                   # the rest of the repo stays behind
        })

    monkeypatch.setattr(cam, "http_get", fake_get)
    monkeypatch.setattr(cam.subprocess, "run", _no_gh)

    assert mgr._template_dir() == cache
    assert urls == [cam.AppManager.TEMPLATE_TARBALL]
    assert (cache / "src" / "__APP_CLASS__App.cpp.tmpl").read_bytes() == b"// app\n"
    assert (cache / "CMakeLists.txt.tmpl").read_bytes() == b"# __APP_ID__\n"
    assert not (cache / "registry.json").exists()
    assert not list(cache.parent.rglob("escape.txt"))
    assert [p.name for p in cache.parent.iterdir()] == ["template"]   # no staging left


def test_without_a_network_the_template_comes_through_gh(tmp_path, monkeypatch):
    mgr, cache = _platform_layout(tmp_path, monkeypatch)

    def no_network(url, timeout=None):
        raise cam.NetError("could not resolve host", offline=True)

    tree = {"template": [("dir", "src"), ("file", "CMakeLists.txt.tmpl")],
            "template/src": [("file", "App.cpp.tmpl")]}
    blobs = {"template/CMakeLists.txt.tmpl": b"# from gh\n",
             "template/src/App.cpp.tmpl": b"// from gh\n"}

    def fake_gh(cmd, **kwargs):
        assert cmd[:2] == ["gh", "api"]
        path = cmd[2].split("/contents/", 1)[1]
        if path in tree:
            out = "".join(f"{kind}\t{name}\t{path}/{name}\n" for kind, name in tree[path])
        else:
            out = base64.b64encode(blobs[path]).decode() + "\n"
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(cam, "http_get", no_network)
    monkeypatch.setattr(cam.subprocess, "run", fake_gh)

    assert mgr._template_dir() == cache
    assert (cache / "CMakeLists.txt.tmpl").read_bytes() == b"# from gh\n"
    assert (cache / "src" / "App.cpp.tmpl").read_bytes() == b"// from gh\n"


def test_a_template_fetched_within_the_hour_is_used_without_the_network(tmp_path, monkeypatch):
    mgr, cache = _platform_layout(tmp_path, monkeypatch)
    _template(cache)

    def no_fetch(*args, **kwargs):
        raise AssertionError("a fresh cache must not be fetched again")

    monkeypatch.setattr(cam, "http_get", no_fetch)
    monkeypatch.setattr(cam.subprocess, "run", no_fetch)
    assert mgr._template_dir() == cache


def test_an_old_template_is_refreshed_and_kept_when_nothing_answers(tmp_path, monkeypatch):
    mgr, cache = _platform_layout(tmp_path, monkeypatch)
    _template(cache)
    old = time.time() - cam.CACHE_MAX_AGE_SECONDS - 60
    os.utime(cache, (old, old))

    def no_network(url, timeout=None):
        raise cam.NetError("could not resolve host", offline=True)

    def gh_missing(cmd, **kwargs):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(cam, "http_get", no_network)
    monkeypatch.setattr(cam.subprocess, "run", gh_missing)
    assert mgr._template_dir() == cache                       # stale beats nothing
    assert (cache / "src" / "__APP_ID__.cpp.tmpl").exists()

    monkeypatch.setattr(cam, "http_get", lambda url, timeout=None: _tarball(
        {"template/src/New.cpp.tmpl": b"// new\n"}))
    assert mgr._template_dir() == cache
    assert (cache / "src" / "New.cpp.tmpl").exists()
    assert not (cache / "src" / "__APP_ID__.cpp.tmpl").exists()   # dropped upstream, gone here
