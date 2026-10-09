import re

import crosspad_app_manager as cam
from tests.hil_fakes import DEV, plain

NOW = 1_000_000.0
HOLDER = {"client": "crosspad-hil", "purpose": "kit_churn", "pid": 4121, "since": NOW - 180}
BG24 = re.compile(r"\x1b\[48;2;(\d+);(\d+);(\d+)m")
FREE = {"device": "dev_6dd8", "lease": None, "queue": []}
PIDF = {"holder": "pidf", "purpose": "firmware_app", "since": NOW - 600, "ttl_s": 1800,
        "expires": NOW + 720}


def colors_with(**at):
    c = ["000000"] * 16
    for idx, hexrgb in at.items():
        c[int(idx[1:])] = hexrgb
    return c


def test_rgb_to_256_takes_the_cube_or_the_grey_ramp():
    assert cam.rgb_to_256(255, 0, 0) == 196
    assert cam.rgb_to_256(0, 0, 0) == 16
    assert cam.rgb_to_256(255, 255, 255) == 231
    assert cam.rgb_to_256(128, 128, 128) == 244


def test_color_mode_follows_colorterm(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(cam, "PLAIN", False)
    monkeypatch.setenv("COLORTERM", "truecolor")
    assert cam.color_mode() == "24bit"
    monkeypatch.setenv("COLORTERM", "24bit")
    assert cam.color_mode() == "24bit"
    monkeypatch.delenv("COLORTERM")
    assert cam.color_mode() == "256"
    monkeypatch.setenv("NO_COLOR", "1")
    assert cam.color_mode() == "none"


def test_grid_puts_pad_12_top_left_and_pad_0_bottom_left():
    lines = cam.pad_grid_lines(colors_with(p12="FF0000", p0="00FF00"), set(), "24bit")
    assert len(lines) == 11                         # four rows of two lines, three gaps
    assert BG24.findall(lines[0])[0] == ("255", "0", "0")
    assert BG24.findall(lines[9])[0] == ("0", "255", "0")
    assert "1" in plain([lines[0]]) and "12" in plain([lines[1]])


def test_grid_falls_back_to_256_colours():
    lines = cam.pad_grid_lines(colors_with(p12="FF0000"), set(), "256")
    assert lines[0].startswith("  \x1b[48;5;196m")
    assert "\x1b[48;2;" not in "".join(lines)


def test_grid_without_colour_names_each_colour():
    text = "".join(cam.pad_grid_lines(colors_with(p12="ff8800"), set(), "none"))
    assert "FF8800" in text and "\x1b[" not in text


def test_grid_marks_held_pads():
    assert "1*" in plain(cam.pad_grid_lines(colors_with(), {12}, "none"))


def test_grid_survives_a_short_or_bad_colour_list():
    lines = cam.pad_grid_lines(["zz"], set(), "24bit")
    assert BG24.findall(lines[0])[0] == ("0", "0", "0")


def test_pad_keys_hit_and_hold():
    assert cam.pad_for_key("1") == (12, False)
    assert cam.pad_for_key("r") == (11, False)
    assert cam.pad_for_key("v") == (3, False)
    assert cam.pad_for_key("!") == (12, True)
    assert cam.pad_for_key("Q") == (8, True)
    assert cam.pad_for_key("V") == (3, True)
    for other in ("", "enter", "l", "5", "tab"):
        assert cam.pad_for_key(other) is None


def test_status_line_is_the_spec_line_with_the_bench():
    hub = {"running": True, "clients": [{"client": "cp-tools"}, {"client": "crosspad-mcp"}],
           "lease": HOLDER}
    assert cam.status_line(DEV, hub, FREE, NOW, "cp-tools") == \
        "v2 · CDC · bench: free · hub: 2 clients · lease: kit_churn (pid 4121, 3 min)"
    hub_free = {**hub, "lease": None}
    assert cam.status_line(DEV, hub_free, {**FREE, "lease": PIDF}, NOW, "cp-tools") == \
        "v2 · CDC · bench: pidf (firmware_app, 12 min left) · hub: 2 clients · lease: -"


def test_status_line_without_board_hub_or_bench():
    assert cam.status_line(None, None, None, NOW, "cp-tools") == "no board · hub: ?"
    assert cam.status_line({**DEV, "usb_mode": "audio"}, {"running": False}, None, NOW,
                           "cp-tools") == "v2 · USB audio · bench: ? · hub: off"
    assert cam.status_line(DEV, {"running": True, "clients": [{}], "lease": None}, FREE, NOW,
                           "cp-tools") == "v2 · CDC · bench: free · hub: 1 client · lease: -"


def test_bench_segment_says_whose_it_is():
    mine = {**PIDF, "holder": "cp-tools"}
    assert cam.bench_segment({**FREE, "lease": mine}, "cp-tools", NOW) == "bench: yours (12 min left)"
    queued = {**FREE, "lease": PIDF, "queue": [{"holder": "codex", "position": 1},
                                               {"holder": "cp-tools", "position": 2}]}
    assert cam.bench_segment(queued, "cp-tools", NOW) == \
        "bench: pidf (firmware_app, 12 min left), you #2"
    reserved = {**FREE, "reserved_for": {"holder": "pidf", "until": NOW + 480}}
    assert cam.bench_segment(reserved, "cp-tools", NOW) == "bench: held for pidf"
    assert cam.bench_segment({**FREE, "reserved_for": {"holder": "cp-tools", "until": NOW}},
                             "cp-tools", NOW) == "bench: free"


def test_bench_busy_lines_from_the_refusal():
    err = cam.HilFailure("BENCH_BUSY", "dev_6dd8 is claimed by pidf", details={
        "holder": "pidf", "purpose": "firmware_app", "since": NOW - 600, "expires": NOW + 720,
        "queue": ["codex", "cp-tools"]})
    text = plain(cam.bench_busy_lines(err, None, NOW, "cp-tools", "c"))
    assert "The bench is claimed" in text and "pidf (firmware_app), since" in text
    assert "12 min left" in text and "queue: codex, cp-tools (you)" in text
    assert "[c] leave the queue" in text and "comes back by itself" in text


def test_bench_busy_lines_prefer_the_live_view():
    err = cam.HilFailure("BENCH_BUSY", "held", details={"holder": "pidf", "expires": NOW + 720})
    view = {**FREE, "reserved_for": {"holder": "pidf", "until": NOW + 480}}
    text = plain(cam.bench_busy_lines(err, view, NOW, "cp-tools", "b"))
    assert "held for pidf, first in the queue, for 8 min more" in text
    assert "[b] join the queue" in text and "12 min" not in text


def test_busy_lines_name_the_holder_and_its_age():
    err = cam.HilFailure("PORT_BUSY", "busy", details={"holder": HOLDER})
    text = plain(cam.busy_lines(err, NOW))
    assert "crosspad-hil (kit_churn), pid 4121, for 3 min" in text
    assert "comes back by itself" in text


def test_busy_lines_without_a_holder_show_the_message():
    err = cam.HilFailure("PORT_BUSY", "/dev/ttyACM0 is held by pid 77 (chrome)")
    assert "held by pid 77" in plain(cam.busy_lines(err, NOW))


def test_missing_hil_says_how_to_install_and_nothing_else():
    text = plain(cam.hil_missing_lines())
    assert f"pip install {cam.HIL_GIT_URL}" in text and "installer" in text
    assert "Pads" not in text


def test_dead_hil_says_how_to_upgrade():
    err = cam.HilFailure(cam.HIL_EXITED, "crosspad-hil stopped: unrecognized arguments: --client")
    text = plain(cam.hil_dead_lines(err))
    assert "unrecognized arguments" in text and f"pip install --upgrade {cam.HIL_GIT_URL}" in text
