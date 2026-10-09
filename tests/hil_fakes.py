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
