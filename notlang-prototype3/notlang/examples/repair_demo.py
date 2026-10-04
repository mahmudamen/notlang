"""Phase-4 preview: the repair loop, with a scripted stand-in for an LLM.

A real loop would send `feedback` to a model and get a new graph back. Here the
"AI" is a script that makes the classic slip (compares Money with an Int), reads
the structured error, and fixes it. Run: python examples/repair_demo.py
"""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from mizan import MizanError, run  # noqa: E402


def load(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


GOOD = load("partner_total.json")


def scripted_ai(feedback):
    if feedback is None:                       # first attempt: the slip
        g = copy.deepcopy(GOOD)
        g["nodes"]["zero_m"] = {"op": "const", "type": "Int", "value": 0}
        return g
    if feedback["code"] == "TYPE_MISMATCH":    # reads the error, repairs
        return GOOD
    raise SystemExit("my script only knows one trick")


def main():
    db, feedback = load("db.json"), None
    for attempt in range(1, 4):
        graph = scripted_ai(feedback)
        print(f"--- attempt {attempt} ---")
        try:
            r = run(graph, {"pid": 1}, db, granted={"db.read"})
        except MizanError as e:
            feedback = e.to_dict()
            print("interpreter -> AI:", json.dumps(feedback))
            continue
        print(f"accepted {r.hash}, result = {r.value}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
