"""A stand-in for `crosspad-hil serve`: NDJSON on stdio, answers from a JSON table.

FAKE_HIL_TABLE names a JSON file {op: spec}. A spec is {"result": ...} or
{"error": {...wire error...}}, optionally with "sleep": seconds before the
answer. Unknown ops answer BAD_ARGS. The op "die" exits at once, unanswered.
Before anything it writes a log line to stderr and an event to stdout, which a
client must ignore. Every request is answered on its own thread, so a slow op
answers after a fast one sent later -- what the client's id matching is for.
"""
import json
import os
import sys
import threading
import time


def main():
    with open(os.environ["FAKE_HIL_TABLE"], encoding="utf-8") as f:
        table = json.load(f)
    out_lock = threading.Lock()

    def emit(obj):
        with out_lock:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()

    sys.stderr.write("fake hil: ready\n")
    sys.stderr.flush()
    emit({"ev": "hello"})

    def answer(req):
        spec = table.get(req.get("op"))
        if spec is None:
            emit({"id": req.get("id"), "ok": False,
                  "error": {"code": "BAD_ARGS", "message": "unknown op", "hint": None, "details": {}}})
            return
        time.sleep(spec.get("sleep", 0))
        if "error" in spec:
            emit({"id": req["id"], "ok": False, "error": spec["error"]})
        else:
            emit({"id": req["id"], "ok": True, "result": spec.get("result")})

    for line in sys.stdin:
        req = json.loads(line)
        if req.get("op") == "die":
            sys.stderr.write("fake hil: going away\n")
            sys.stderr.flush()
            os._exit(3)
        threading.Thread(target=answer, args=(req,), daemon=True).start()


if __name__ == "__main__":
    main()
