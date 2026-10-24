import crosspad_app_manager as cam
from tests.hil_fakes import BASE, BENCH_FREE, WALL, FakeHil, make_screen, plain, settle

PIDF = {"holder": "pidf", "purpose": "firmware_app", "since": WALL - 600, "ttl_s": 1800,
        "expires": WALL + 720}
TAKEN = {**BENCH_FREE, "lease": PIDF}
MINE = {**BENCH_FREE, "lease": {"holder": "cp-tools", "purpose": "CP Tools CrossPad screen",
                                "since": WALL, "ttl_s": 1800, "expires": WALL + 1800}}
BENCH_BUSY_ERR = {"code": "BENCH_BUSY", "message": "dev_6dd8 is claimed by pidf (firmware_app)",
                  "hint": "claim it to join the queue",
                  "details": {"holder": "pidf", "purpose": "firmware_app", "since": WALL - 600,
                              "expires": WALL + 720, "queue": []}}
BUSY = {**BASE, "bench.status": {"result": {"devices": [TAKEN]}},
        "cdc.verb:led_state": {"error": BENCH_BUSY_ERR},
        "cdc.verb:ui_state": {"error": BENCH_BUSY_ERR},
        "cdc.verb:enc_focus": {"error": BENCH_BUSY_ERR}}


def bench_calls(fake, op):
    return [a for o, a in fake.calls if o == op]


def test_every_board_op_names_the_holder_and_only_board_ops_do():
    fake = FakeHil(BASE)
    s = make_screen(fake)
    settle(s)
    s.handle_key("z")
    board = [a for op, a in fake.calls if op not in cam.HIL_UNBOUND_OPS]
    assert board and all(a["holder"] == "cp-tools" for a in board)
    assert all("holder" not in a for op, a in fake.calls if op in cam.HIL_UNBOUND_OPS)


def test_the_machines_holder_name_is_used(monkeypatch):
    monkeypatch.setenv("CROSSPAD_BENCH_HOLDER", "pidf")
    fake = FakeHil(BASE)
    s = make_screen(fake)
    settle(s)
    s.handle_key("z")
    assert fake.calls[-1][1]["holder"] == "pidf"


def test_someone_elses_bench_shows_who_and_comes_back():
    t = [100.0]
    fake = FakeHil(BUSY)
    s = make_screen(fake, t=t)
    settle(s)
    lines = s.render(100, 30)
    text = plain(lines)
    assert "bench: pidf (firmware_app, 12 min left)" in text
    assert "The bench is claimed" in text and "pidf (firmware_app), since" in text
    assert "[b] join the queue" in text
    assert "\x1b[48;" not in "".join(lines)
    s.handle_key("1")
    assert fake.verb_calls("pad_press") == []
    fake.table.update(BASE)                 # pidf gave the bench back
    t[0] = 101.1
    settle(s, 2)
    lines = s.render(100, 30)
    assert "The bench is claimed" not in plain(lines)
    assert "\x1b[48;" in "".join(lines)          # the grid is back


def test_off_pads_the_claim_key_is_c():
    fake = FakeHil(BUSY)
    s = make_screen(fake)
    settle(s)
    s.handle_key("tab")                     # Trace: the bench is still someone else's
    assert "[c] join the queue" in plain(s.render(100, 30))
    assert "[c] claim or release the bench" in s.hints()


def test_on_pads_c_is_a_pad_and_b_claims():
    fake = FakeHil({**BASE, "bench.claim": {"result": {**BENCH_FREE, "granted": False,
                                                       "position": 1}}})
    s = make_screen(fake)
    settle(s)
    s.handle_key("c")
    assert fake.verb_calls("pad_press") == [{"idx": 2, "vel": 100}]
    assert bench_calls(fake, "bench.claim") == []
    s.handle_key("b")
    assert len(bench_calls(fake, "bench.claim")) == 1
    assert "[b] claim or release the bench" in s.hints()


def test_a_queued_claim_shows_its_place_and_asks_again():
    t = [100.0]
    queued = {**TAKEN, "granted": False, "holder": "cp-tools", "position": 1,
              "queue": [{"holder": "cp-tools", "position": 1}]}
    fake = FakeHil({**BUSY, "bench.claim": {"result": queued}})
    s = make_screen(fake, t=t)
    settle(s)
    s.handle_key("b")
    s.tick()
    assert bench_calls(fake, "bench.claim") == [{
        "device": "dev_6dd8", "holder": "cp-tools",
        "purpose": cam._DeviceScreen.BENCH_PURPOSE, "ttl_s": cam._DeviceScreen.BENCH_TTL_S}]
    assert "Queued for the bench: #1 behind pidf" in plain(s.render(100, 30))
    t[0] += cam._DeviceScreen.BENCH_REQUEUE_S + 0.5
    s.tick()
    assert len(bench_calls(fake, "bench.claim")) == 2


def claimed(t):
    fake = FakeHil({**BASE, "bench.claim": {"result": {**MINE, "granted": True,
                                                       "holder": "cp-tools"}},
                    "bench.renew": {"result": {**MINE, "renewed": True}},
                    "bench.release": {"result": {**BENCH_FREE, "released": True,
                                                 "left_queue": False}},
                    "cdc.verb:app_sha": {"result": {"sha256": "ab" * 32}}})
    s = make_screen(fake, t=t)
    settle(s)
    s.handle_key("b")
    s.tick()
    fake.table["bench.status"] = {"result": {"devices": [MINE]}}
    return fake, s


def test_a_granted_claim_is_renewed_at_half_its_ttl():
    t = [100.0]
    fake, s = claimed(t)
    assert "bench: yours (30 min left)" in plain(s.render(100, 30))
    t[0] = 100.0 + cam._DeviceScreen.BENCH_TTL_S / 2 - 1
    s.tick()
    assert bench_calls(fake, "bench.renew") == []
    t[0] += 2
    s.tick()
    assert bench_calls(fake, "bench.renew") == [{"device": "dev_6dd8", "holder": "cp-tools",
                                                  "ttl_s": cam._DeviceScreen.BENCH_TTL_S}]


def test_the_key_again_gives_it_back_saying_what_firmware_is_on_it():
    t = [100.0]
    fake, s = claimed(t)
    t[0] += 1.1
    s.tick()
    s.handle_key("b")
    settle(s, 2)
    assert bench_calls(fake, "bench.release") == [{
        "device": "dev_6dd8", "holder": "cp-tools", "firmware_left": "app_sha256 " + "ab" * 8}]
    assert "Gave the bench back" in plain(s.render(100, 30))


def test_leaving_gives_the_bench_back():
    t = [100.0]
    fake, s = claimed(t)
    t[0] += 1.1
    s.tick()
    assert s.handle_key("esc") is False
    s.leave()
    assert bench_calls(fake, "bench.release") == [{
        "device": "dev_6dd8", "holder": "cp-tools", "firmware_left": "app_sha256 " + "ab" * 8}]


def test_leaving_without_a_claim_releases_nothing():
    fake = FakeHil({**BASE, "bench.status": {"result": {"devices": [MINE]}}})
    s = make_screen(fake)
    settle(s)
    s.leave()
    assert bench_calls(fake, "bench.release") == []
