import crosspad_app_manager as cam
from tests.hil_fakes import BASE, FakeHil, make_screen, plain, settle

HEAP = {"groups": [{"bytes": 4096, "count": 2, "pc": ["0x4200abcd", "0x4200ef01"]}],
        "records": 2, "on": 1}
TOUCH = {"samples": [{"t_ms": 10, "pressed": True, "x": 100, "y": 50},
                     {"t_ms": 30, "pressed": False, "x": 180, "y": 52}],
         "n": 2, "on": 1, "swipes": 1, "last": "right"}


def test_heap_lines_carry_groups_and_trailer():
    text = plain(cam.heap_trace_lines(HEAP))
    assert "records=2 on=1" in text and "bytes=4096 count=2 pc=0x4200abcd,0x4200ef01" in text
    assert "no allocations" in plain(cam.heap_trace_lines({"groups": []}))


def test_touch_lines_carry_samples_and_counters():
    text = plain(cam.touch_trace_lines(TOUCH))
    assert "swipes=1" in text and "last=right" in text and "x=180 y=52" in text


def test_dump_lands_in_the_pane_and_s_saves_it(tmp_path):
    fake = FakeHil({**BASE, "cdc.verb:heap_trace": {"result": HEAP}})
    s = make_screen(fake, tab=cam.DEV_TAB_TRACE, project_dir=tmp_path)
    settle(s)
    s.handle_key("right")
    s.handle_key("right")                   # Heap dump
    s.handle_key("enter")
    s.tick()
    assert fake.verb_calls("heap_trace") == [{"what": "DUMP"}]
    assert "bytes=4096" in plain(s.render(100, 30))
    s.handle_key("s")
    saved = list((tmp_path / ".crosspad" / "traces").glob("*.txt"))
    assert len(saved) == 1
    body = saved[0].read_text(encoding="utf-8")
    assert "bytes=4096" in body and "\x1b[" not in body
    assert "Saved .crosspad" in plain(s.render(100, 30))


def test_every_action_sends_its_word():
    fake = FakeHil({**BASE, "cdc.verb:heap_trace": {"result": HEAP},
                    "cdc.verb:touch_trace": {"result": TOUCH}})
    s = make_screen(fake, tab=cam.DEV_TAB_TRACE)
    settle(s)
    for _ in cam.TRACE_ACTIONS:
        s.handle_key("enter")
        s.tick()
        s.handle_key("right")
    assert [a["what"] for a in fake.verb_calls("heap_trace")] == ["START", "STOP", "DUMP"]
    assert [a["what"] for a in fake.verb_calls("touch_trace")] == ["ON", "OFF", "CLEAR", "DUMP"]


def test_the_pane_scrolls(tmp_path):
    many = {"samples": [{"t_ms": i, "pressed": True, "x": i, "y": i} for i in range(60)], "n": 60}
    fake = FakeHil({**BASE, "cdc.verb:touch_trace": {"result": many}})
    s = make_screen(fake, tab=cam.DEV_TAB_TRACE)
    settle(s)
    s.render(100, 30)                       # the pane is as tall as the last draw made it
    s.trace_pick = 6                        # Touch dump
    s.handle_key("enter")
    s.tick()
    assert s.trace_top == len(s.trace_out) - s._pane      # follows the newest output
    s.handle_key("home")
    assert s.trace_top == 0
    s.handle_key("pgdn")
    assert s.trace_top == s._pane


def test_nothing_to_save_says_so(tmp_path):
    s = make_screen(FakeHil(BASE), tab=cam.DEV_TAB_TRACE, project_dir=tmp_path)
    settle(s)
    s.handle_key("s")
    assert "Nothing to save" in plain(s.render(100, 30))
    assert not (tmp_path / ".crosspad").exists()
