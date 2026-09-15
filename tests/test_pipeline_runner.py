import crosspad_app_manager as cam


class FakeUI:
    def __init__(self, local="leave", board="v2"):
        self.frames, self.local, self.board = [], local, board
        self.asked = []
    def render(self, steps, tail, progress):
        self.frames.append([(s.name, s.ok, s.detail) for s in steps])
    def ask_local_work(self, app):
        self.asked.append(app); return self.local
    def ask_board(self, revs):
        return self.board
    def wait_for_board(self, probe):
        return True
    def cancelled(self):
        return False


class FakeMgr:
    """Just enough AppManager for the runner; every subprocess is a stub."""
    class config:
        platform = "esp-idf"
        board_revs = ("v1", "v2")
    def __init__(self, tmp_path):
        self.project_dir = tmp_path
        self.calls, self.board = [], {"rev": "v2", "source": "device", "build_dir": "build_v2"}
        self.statuses = {"sampler": {"app": "sampler", "path": "components/crosspad-sampler",
                                     "blocking": [], "policy": {"track": "registry"},
                                     "git": {"exists": True, "head": "b048ab8"}},
                         "dawcontrol": {"app": "dawcontrol", "path": "components/crosspad-dawcontrol",
                                        "blocking": ["dirty"], "policy": {"track": "registry"},
                                        "git": {"exists": True, "head": "67be174"}}}
        self.flash_rc, self.build_rc, self.diff = 0, 0, {"ok": True, "stale": []}
    def _load_manifest(self):
        return {"installed": {k: {} for k in self.statuses}}
    def app_status(self, a): return self.statuses[a]
    def app_display_name(self, a): return a.capitalize()
    def backup_app(self, a): self.calls.append(("backup", a)); return "/bk"
    def update(self, app_name=None, update_all=False, force=False, dry_run=False):
        self.calls.append(("update", app_name, force))
    def infra_submodules(self): return ["components/crosspad-core"]
    def _git(self, *args, check=True, capture=False):
        self.calls.append(("git",) + args)
        class R: returncode = 0; stdout = ""
        return R()
    def board_info(self, refresh=False): return self.board
    def idf_args(self): return "-B build_v2 -DSDKCONFIG=sdkconfig.v2 "
    def run_streaming(self, cmd, on_line, log=None):
        self.calls.append(("run", cmd))
        on_line("[10/20] Building CXX object x.obj")
        return self.build_rc
    def device_probe(self): return {"ports": {"cdc": {"path": "/dev/ttyACM1"}}}
    def device_diff(self): return self.diff
    def last_update(self): return None
    def save_last_update(self, rec): self.saved = rec
    def get_all_submodules(self): return []
    def component_path(self, c): return None
    flash_ota = staticmethod(lambda rev, on_line: 0)


def test_pipeline_happy_path(tmp_path):
    mgr = FakeMgr(tmp_path)
    mgr.config.flash_ota = lambda rev, on_line: 0
    ui = FakeUI()
    p = cam.UpdatePipeline(mgr, ui)
    assert p.run() is True
    names = [c[0] for c in mgr.calls]
    assert ("update", "sampler", False) in mgr.calls
    assert ("update", "dawcontrol", False) not in mgr.calls       # left alone
    assert ui.asked == ["Dawcontrol"]
    assert any(c[0] == "run" and "fullclean" in c[1] for c in mgr.calls)   # no record → fullclean
    assert mgr.saved["ok"] and [s["name"] for s in mgr.saved["steps"]] == list(cam.STEP_NAMES)
    assert all(s.ok for s in p.steps)


def test_pipeline_backup_then_update_local_work(tmp_path):
    mgr = FakeMgr(tmp_path)
    mgr.config.flash_ota = lambda rev, on_line: 0
    p = cam.UpdatePipeline(mgr, FakeUI(local="backup"))
    p.run()
    assert ("backup", "dawcontrol") in mgr.calls
    assert ("update", "dawcontrol", True) in mgr.calls


def test_pipeline_build_failure_stops_with_the_error_line(tmp_path):
    mgr = FakeMgr(tmp_path)
    mgr.config.flash_ota = lambda rev, on_line: 0
    mgr.build_rc = 1
    p = cam.UpdatePipeline(mgr, FakeUI())
    assert p.run() is False
    build = p.step("build")
    assert build.ok is False and build.error.startswith("Build failed in")
    assert p.step("flash").ok is None
    assert mgr.saved["ok"] is False


def test_pipeline_asks_for_the_board_only_when_unresolved(tmp_path):
    mgr = FakeMgr(tmp_path)
    mgr.config.flash_ota = lambda rev, on_line: 0
    mgr.board = {"rev": None, "source": "none"}
    chosen = []
    mgr.config.board_set = lambda rev: chosen.append(rev) or mgr.board.update(rev="v2", build_dir="build_v2")
    p = cam.UpdatePipeline(mgr, FakeUI(board="v2"))
    assert p.run() is True
    assert chosen == ["v2"]


def test_pipeline_check_mismatch(tmp_path):
    mgr = FakeMgr(tmp_path)
    mgr.config.flash_ota = lambda rev, on_line: 0
    mgr.diff = {"ok": True, "stale": [{"component": "crosspad-sampler", "app_id": "sampler"}]}
    p = cam.UpdatePipeline(mgr, FakeUI())
    assert p.run() is False
    assert p.step("check").error == "The board still runs the old Sampler → [r] flash again"


def test_pipeline_without_flash_hook_stops_after_build(tmp_path):
    mgr = FakeMgr(tmp_path)
    if hasattr(mgr.config, "flash_ota"):
        del mgr.config.flash_ota
    p = cam.UpdatePipeline(mgr, FakeUI())
    assert p.run() is True
    assert [s.name for s in p.steps] == ["download", "components", "build"]
