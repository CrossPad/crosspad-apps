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
