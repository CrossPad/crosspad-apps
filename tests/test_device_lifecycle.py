"""Leaving the screen gives back what it took: pads, and the bench it claimed."""
import threading
from concurrent.futures import Future

import crosspad_app_manager as cam
from tests.hil_fakes import BASE, BENCH_FREE, WALL, FakeHil, make_screen, settle

MINE = {**BENCH_FREE, "lease": {"holder": "cp-tools", "purpose": "CP Tools CrossPad screen",
                                "since": WALL, "ttl_s": 1800, "expires": WALL + 1800}}


class HeldHil(FakeHil):
    """FakeHil whose ops named in `hold` stay unanswered until the test answers them."""

    def __init__(self, table, hold=()):
        super().__init__(table)
        self.hold, self.held = set(hold), []

    def submit(self, op, args=None):
        key = f"{op}:{(args or {}).get('verb')}" if op == "cdc.verb" else op
        if key in self.hold:
            self.calls.append((op, dict(args or {})))
            fut = Future()
            self.held.append((key, fut))
            return fut
        return super().submit(op, args)

    def answer(self, key, result):
        for k, fut in self.held:
            if k == key and not fut.done():
                fut.set_result(result)
                return
        raise AssertionError(f"nothing held for {key}")


def releases(fake):
    return [a for op, a in fake.calls if op == "bench.release"]


def test_release_pressed_while_the_claim_is_in_flight_gives_the_bench_back():
    fake = HeldHil(BASE, hold={"bench.claim"})
    s = make_screen(fake)
    settle(s)
    s.handle_key("b")                         # claim
    s.handle_key("b")                         # changed my mind before it answered
    fake.answer("bench.claim", {"granted": True, **MINE})
    fake.table["bench.status"] = {"result": {"devices": [MINE]}}
    settle(s, 3)
    assert releases(fake), "the granted claim was never given back"


def test_leave_right_after_the_release_key_still_gives_the_bench_back():
    fake = HeldHil({**BASE, "bench.status": {"result": {"devices": [MINE]}},
                    "bench.claim": {"result": {"granted": True, **MINE}}},
                   hold={"cdc.verb:app_sha"})
    s = make_screen(fake)
    settle(s)
    s.handle_key("b")
    settle(s, 2)
    s.handle_key("b")                         # release: waits on app_sha
    s.leave()
    assert releases(fake)


def test_leave_gives_the_bench_back_when_the_board_is_gone():
    fake = FakeHil({**BASE, "bench.status": {"result": {"devices": [MINE]}},
                    "bench.claim": {"result": {"granted": True, **MINE}}})
    s = make_screen(fake)
    settle(s)
    s.handle_key("b")
    settle(s, 2)
    s.dev = None                              # NO_DEVICE while the board re-enumerates
    s.leave()
    assert releases(fake) and releases(fake)[-1]["device"] == "dev_6dd8"


def test_a_lease_by_another_window_with_our_name_is_not_released_here():
    fake = FakeHil({**BASE, "bench.status": {"result": {"devices": [MINE]}},
                    "bench.claim": {"result": {"granted": True, **MINE}}})
    s = make_screen(fake)
    settle(s)
    s.handle_key("b")                         # this screen never claimed: the key claims
    assert [op for op, _ in fake.calls if op.startswith("bench.c")] == ["bench.claim"]
    assert releases(fake) == []


def test_leave_never_releases_a_claim_this_screen_did_not_make():
    fake = FakeHil({**BASE, "bench.status": {"result": {"devices": [MINE]}}})
    s = make_screen(fake)
    settle(s)
    s.leave()
    assert releases(fake) == []


def test_leave_waits_for_an_unanswered_press_before_releasing_the_pad():
    fake = HeldHil(BASE, hold={"cdc.verb:pad_press"})
    s = make_screen(fake)
    settle(s)
    s.handle_key("z")                         # pad 0 hit, press not answered yet
    order = []
    orig = fake.submit

    def spy(op, args=None):
        if op == "cdc.verb" and (args or {}).get("verb") == "pad_release":
            order.append(("release", all(f.done() for k, f in fake.held)))
        return orig(op, args)

    fake.submit = spy
    t = threading.Timer(0.3, lambda: fake.answer("cdc.verb:pad_press", {"ok": True}))
    t.start()
    s.leave()
    t.join()
    assert order and order[0] == ("release", True)


def test_a_modal_lets_go_of_a_hit_pad_first():
    fake = FakeHil({**BASE, "cdc.verb:app_list": {"result": {"apps": ["Sampler"],
                                                             "running": None}}})
    s = make_screen(fake)
    settle(s)
    s.handle_key("z")
    seen = []
    orig = cam._menu_select
    cam._menu_select = lambda *a, **k: (seen.append(len(fake.verb_calls("pad_release"))), -1)[1]
    try:
        s.handle_key("l")
    finally:
        cam._menu_select = orig
    assert seen == [1]


def test_scrub_cleans_keys_too():
    out = cam._scrub({"\x1b]52;c;QQ==\x07": {"/sd\x1b[2J": 1}})
    (k, v), = out.items()
    assert "\x1b" not in k and "\x07" not in k and "\x1b" not in next(iter(v))
