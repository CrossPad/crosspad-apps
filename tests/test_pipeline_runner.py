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
    def run_streaming(self, cmd, on_line, log=None, cancel=None):
        self.calls.append(("run", cmd))
        on_line("[10/20] Building CXX object x.obj")
        return self.build_rc
    chosen_device = None
    def devices(self): return []
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
    # _download no longer backs up itself — update(force=True) does that
    # through guard() (a real AppManager's own path), so a second, identical
    # snapshot is not taken here.
    assert ("backup", "dawcontrol") not in mgr.calls
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


def test_pipeline_flash_output_reaches_the_log(tmp_path):
    mgr = FakeMgr(tmp_path)
    mgr.config.flash_ota = lambda rev, on_line: (on_line("ota: 50%"), 0)[1]
    p = cam.UpdatePipeline(mgr, FakeUI())
    assert p.run() is True
    log = (tmp_path / ".crosspad" / "last-update.log").read_text()
    assert "ota: 50%" in log


def test_pipeline_retry_from_build_appends_log_and_skips_download(tmp_path):
    mgr = FakeMgr(tmp_path)
    mgr.config.flash_ota = lambda rev, on_line: 0
    mgr.build_rc = 1
    p = cam.UpdatePipeline(mgr, FakeUI())
    assert p.run() is False
    update_calls_after_first_run = len([c for c in mgr.calls if c[0] == "update"])

    mgr.build_rc = 0
    assert p.retry_from("build") is True
    assert p.step("download").ok is True
    update_calls_after_retry = len([c for c in mgr.calls if c[0] == "update"])
    assert update_calls_after_retry == update_calls_after_first_run   # not re-run
    assert p.step("flash").ok is True
    assert p.step("check").ok is True
    log = (tmp_path / ".crosspad" / "last-update.log").read_text()
    assert "== Download updates ==" in log   # first run's header survived (append)


def test_pipeline_board_set_raising_fails_the_build_step(tmp_path):
    mgr = FakeMgr(tmp_path)
    mgr.config.flash_ota = lambda rev, on_line: 0
    mgr.board = {"rev": None, "source": "none"}

    def raising_board_set(rev):
        raise RuntimeError("boom")
    mgr.config.board_set = raising_board_set
    p = cam.UpdatePipeline(mgr, FakeUI(board="v2"))
    assert p.run() is False
    build = p.step("build")
    assert build.ok is False
    assert build.error == cam.error_line("build", "no-board")
    assert mgr.saved["ok"] is False


def test_explain_failure_names_known_causes():
    assert "disk is full" in cam.explain_failure(["x", "ld: No space left on device"])
    assert "path too long" in cam.explain_failure(["fatal: Filename too long"])
    assert "clean build" in cam.explain_failure(
        ["app_registry_init.cpp:(.text+0x1): undefined reference to `_register_sampler_app()'"])
    assert "dialout" in cam.explain_failure(["PermissionError: [Errno 13] Permission denied: '/dev/ttyACM0'"])
    assert cam.explain_failure(["error: expected ';' before '}' token"]) is None


def test_build_failure_with_a_known_cause_says_it_and_forces_a_clean_retry(tmp_path):
    mgr = FakeMgr(tmp_path)
    mgr.config.flash_ota = lambda rev, on_line: 0
    def failing(cmd, on_line, log=None, cancel=None):
        on_line("undefined reference to `_register_fishtank_app()'")
        return 1
    mgr.run_streaming = failing
    p = cam.UpdatePipeline(mgr, FakeUI())
    p.plan["fullclean"] = False
    assert p.run() is False
    assert "clean build" in p.step("build").error and p.plan["fullclean"] is True


def test_stopped_build_is_a_retryable_step_not_a_crash(tmp_path):
    mgr = FakeMgr(tmp_path)
    mgr.config.flash_ota = lambda rev, on_line: 0
    mgr.run_streaming = lambda cmd, on_line, log=None, cancel=None: cam.AppManager.CANCELLED
    p = cam.UpdatePipeline(mgr, FakeUI())
    assert p.run() is False
    assert p.step("build").error.startswith("Stopped")


def test_ctrl_c_inside_a_step_marks_it_stopped(tmp_path):
    mgr = FakeMgr(tmp_path)
    def boom(rev, on_line):
        raise KeyboardInterrupt
    mgr.config.flash_ota = boom
    p = cam.UpdatePipeline(mgr, FakeUI())
    assert p.run() is False
    assert "Flash stopped" in p.step("flash").error


def test_run_streaming_cancel_stops_the_process_tree(tmp_path):
    import sys, time
    mgr = cam.AppManager(str(tmp_path), cam.PlatformConfig(platform="pc"))
    lines = []
    t0 = time.time()
    rc = mgr.run_streaming(f'"{sys.executable}" -c "import time; print(1, flush=True); time.sleep(30)"',
                           lines.append, cancel=lambda: bool(lines))
    assert rc == cam.AppManager.CANCELLED and time.time() - t0 < 10 and lines == ["1"]


def test_two_boards_ask_which_and_the_hook_gets_that_device(tmp_path):
    mgr = FakeMgr(tmp_path)
    mgr.devices = lambda: [{"id": "dev_a"}, {"id": "dev_b"}]
    got = {}
    def ota(rev, on_line, device=None):
        got["device"] = device
        return 0
    mgr.config.flash_ota = ota
    mgr.device_probe = lambda: {"id": mgr.chosen_device, "ports": {"cdc": {"path": "/dev/x"}}}
    ui = FakeUI()
    ui.ask_device = lambda devs: "dev_b"
    assert cam.UpdatePipeline(mgr, ui).run() is True
    assert got["device"] == "dev_b"


def test_an_old_wrapper_hook_without_device_still_flashes(tmp_path):
    mgr = FakeMgr(tmp_path)
    calls = []
    mgr.config.flash_ota = lambda rev, on_line: calls.append(rev) or 0
    assert cam.UpdatePipeline(mgr, FakeUI()).run() is True and calls == ["v2"]


def test_a_successful_update_that_moved_apps_remembers_where_they_were(tmp_path):
    mgr = FakeMgr(tmp_path)
    mgr.config.flash_ota = lambda rev, on_line: 0
    heads = iter([{"sampler": "aaa"}, {"sampler": "bbb"}])
    mgr.app_heads = lambda: next(heads)
    assert cam.UpdatePipeline(mgr, FakeUI()).run() is True
    assert mgr.saved["previous"] == {"sampler": "aaa"} and mgr.saved["after"] == {"sampler": "bbb"}


def test_an_update_that_moved_nothing_keeps_the_older_go_back_point(tmp_path):
    mgr = FakeMgr(tmp_path)
    mgr.config.flash_ota = lambda rev, on_line: 0
    mgr.last_update = lambda: {"ok": True, "previous": {"sampler": "old"}, "after": {"sampler": "aaa"}}
    mgr.app_heads = lambda: {"sampler": "aaa"}
    assert cam.UpdatePipeline(mgr, FakeUI()).run() is True
    assert mgr.saved["previous"] == {"sampler": "old"}


def test_a_checkout_equal_to_the_release_flashes_its_image_without_building(tmp_path):
    mgr = FakeMgr(tmp_path)
    got = {}
    def ota(rev, on_line, device=None, image=None):
        got["image"] = image
        return 0
    mgr.config.flash_ota = ota
    mgr.official_release = lambda: {"tag": "v1.0.2", "assets": {}}
    mgr.release_match = lambda rel: (True, "")
    mgr.download_release_image = lambda rel, rev, on_line=None: tmp_path / "CrossPad-v1.0.2-v2.bin"
    p = cam.UpdatePipeline(mgr, FakeUI())
    assert p.run() is True
    assert not any(c[0] == "run" for c in mgr.calls)             # no compile
    assert got["image"].endswith("CrossPad-v1.0.2-v2.bin")
    assert "ready-built v1.0.2" in p.step("build").detail


def test_a_checkout_that_differs_from_the_release_builds(tmp_path):
    mgr = FakeMgr(tmp_path)
    mgr.config.flash_ota = lambda rev, on_line, device=None, image=None: 0
    mgr.official_release = lambda: {"tag": "v1.0.2", "assets": {}}
    mgr.release_match = lambda rel: (False, "crosspad-sampler is on another version")
    p = cam.UpdatePipeline(mgr, FakeUI())
    assert p.run() is True and any(c[0] == "run" for c in mgr.calls)
    assert "crosspad-sampler is on another version" in (tmp_path / cam.LAST_UPDATE_LOG).read_text()


def test_the_screenless_ui_prints_each_step_once_and_never_asks(tmp_path, capsys):
    mgr = FakeMgr(tmp_path)
    mgr.config.flash_ota = lambda rev, on_line: 0
    assert cam.UpdatePipeline(mgr, cam._PrintUI()).run() is True
    out = capsys.readouterr().out
    for title in ("Download updates", "Firmware components", "Build", "Flash", "Check"):
        assert out.count(f"[OK ] {title}") == 1, out
    assert "Dawcontrol has changes you made — left alone" in out
