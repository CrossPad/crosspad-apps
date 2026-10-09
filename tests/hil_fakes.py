"""In-process stand-ins for crosspad-hil serve, for the screen and manager tests."""
from concurrent.futures import Future

import crosspad_app_manager as cam


class FakeHil:
    """Answers like _HilClient, at once, from a table.

    Keys are the op, or "cdc.verb:<verb>" for a named verb. A value is
    {"result": ...}, {"error": <wire error dict>}, or {"pending": True} for a
    request that never answers. Anything not in the table answers {"ok": True}.
    """

    def __init__(self, table: dict):
        self.table = dict(table)
        self.calls: list[tuple[str, dict]] = []
        self.alive = True

    def submit(self, op, args=None):
        args = dict(args or {})
        self.calls.append((op, args))
        key = f"{op}:{args.get('verb')}" if op == "cdc.verb" else op
        spec = self.table.get(key, {"result": {"ok": True}})
        fut = Future()
        if spec.get("pending"):
            return fut
        if "error" in spec:
            fut.set_exception(cam.HilFailure.from_wire(spec["error"]))
        else:
            fut.set_result(spec["result"])
        return fut

    def request(self, op, args=None, timeout=5.0):
        return self.submit(op, args).result(timeout)

    def close(self):
        self.alive = False

    def verb_calls(self, verb):
        return [a.get("args", {}) for op, a in self.calls
                if op == "cdc.verb" and a.get("verb") == verb]


DEV = {"id": "dev_6dd8", "serial": "CP2-0042", "usb_mode": "default", "board_rev": "v2",
       "pcb": 20, "fw_rev": "v2", "ports": {"cdc": {"path": "/dev/ttyACM0"}}}


def plain(lines) -> str:
    return "\n".join(cam._ANSI_RE.sub("", line) for line in lines)


WALL = 1_000_000.0
HOLDER = {"client": "crosspad-hil", "purpose": "kit_churn", "pid": 4121, "since": WALL - 180}
HUB = {"running": True, "board": "dev_6dd8", "usb_mode": "default", "cdc_open": True,
       "clients": [{"client": "cp-tools", "purpose": "screen", "pid": 11},
                   {"client": "crosspad-mcp", "purpose": "query", "pid": 12}],
       "lease": None}
HUB_LEASED = {**HUB, "lease": HOLDER}
PORT_BUSY_ERR = {"code": "PORT_BUSY", "message": "the board is leased", "hint": None,
                 "details": {"holder": HOLDER}}
LEDS = {"brightness": 40, "anim": False, "coalesce": True, "cfgbri": 40, "pwr": 0,
        "pwr_count": 0, "txfail": 0,
        "colors": ["00FF00"] + ["000000"] * 11 + ["FF0000", "000000", "000000", "000000"]}
UI = {"display": "on", "touch": "on", "drawer": 0, "lcd": 1, "rgb": 1, "theme": 0,
      "bt_icon": None, "app": "Sampler"}
FOCUS = {"index": 2, "label": "KIT", "ptr": "0x3fc9a000", "editing": False}
BENCH_FREE = {"device": "dev_6dd8", "lease": None, "queue": [], "firmware": None, "history": []}
BASE = {"devices.list": {"result": {"devices": [DEV]}},
        "hub.status": {"result": HUB},
        "bench.status": {"result": {"devices": [BENCH_FREE]}},
        "cdc.verb:led_state": {"result": LEDS},
        "cdc.verb:ui_state": {"result": UI},
        "cdc.verb:enc_focus": {"result": FOCUS}}


def make_screen(fake, tab=0, project_dir=".", t=None):
    t = t if t is not None else [100.0]
    return cam._DeviceScreen(fake, tab=tab, project_dir=project_dir,
                             clock=lambda: t[0], wall=lambda: WALL)


def settle(screen, n=3):
    for _ in range(n):
        screen.tick()
