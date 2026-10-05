"""Benchmark seed: can a model write Mizan, and what happens to its mistakes?

Per task it measures: attempts until the checker accepts, and whether the accepted
program is actually correct on the task's cases. "Incorrect-but-accepted" is the
number the paper cares about.

  python -m bench.run_bench --mock                 # offline dry run of the harness
  ANTHROPIC_API_KEY=... python -m bench.run_bench  # real model
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mizan import MizanError, check, run  # noqa: E402
from mizan.ops import parse_value  # noqa: E402


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_system(db):
    spec = (ROOT / "SPEC-001.md").read_text(encoding="utf-8")
    example = (ROOT / "examples" / "has_invoices.json").read_text(encoding="utf-8")
    return (
        "You write programs in Mizan v0.1, a language for AI authors. Programs are JSON graphs.\n"
        "Reply with exactly ONE JSON object and nothing else: no markdown fences, no commentary.\n"
        "If the interpreter returns an error, fix the program and reply with the full corrected JSON.\n\n"
        f"=== SPEC ===\n{spec}\n\n"
        f"=== WORKED EXAMPLE (a different function) ===\n{example}\n\n"
        f"=== DATABASE SCHEMA ===\n{json.dumps(db['schema'], indent=2)}\n"
    )


def extract_json(text):
    t = text.strip()
    try:
        return json.loads(t)
    except ValueError:
        pass
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j <= i:
        raise ValueError("no JSON object found in the reply")
    return json.loads(t[i:j + 1])


def evaluate(graph, task, db):
    """Return (passed, failures) over the task's cases."""
    failures = []
    for case in task["cases"]:
        try:
            r = run(graph, case["args"], db, set(task["needs"]))
        except MizanError as e:
            if case.get("error") != e.code:
                failures.append({"args": case["args"], "got_error": e.code,
                                 "expected": case.get("error") or case.get("expect")})
            continue
        if "error" in case:
            failures.append({"args": case["args"], "got": str(r.value), "expected_error": case["error"]})
        elif r.value != parse_value(task["returns"], case["expect"]):
            failures.append({"args": case["args"], "got": str(r.value), "expected": case["expect"]})
    return not failures, failures


def attempt_task(model, task, db, system, max_attempts):
    messages = [{"role": "user", "content": task["prompt"]}]
    for attempt in range(1, max_attempts + 1):
        text = model.ask(task, system, messages)
        try:
            graph = extract_json(text)
            check(graph, db["schema"])
        except ValueError as e:
            feedback = {"stage": "shape", "code": "BAD_JSON", "message": str(e)}
        except MizanError as e:
            feedback = e.to_dict()
        else:
            ok, failures = evaluate(graph, task, db)
            return {"id": task["id"], "name": task["name"], "attempts": attempt,
                    "accepted": True, "correct": ok, "failures": failures}
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": "Interpreter error: " + json.dumps(feedback)}]
    return {"id": task["id"], "name": task["name"], "attempts": max_attempts,
            "accepted": False, "correct": False, "failures": [], "last_error": feedback}


def run_bench(model, tasks, db, max_attempts=3):
    system = build_system(db)
    return [attempt_task(model, t, db, system, max_attempts) for t in tasks]


def summarize(rows):
    n = len(rows)
    return {
        "tasks": n,
        "first_try_accepted": sum(r["accepted"] and r["attempts"] == 1 for r in rows),
        "accepted_in_budget": sum(r["accepted"] for r in rows),
        "correct": sum(r["correct"] for r in rows),
        "incorrect_but_accepted": sum(r["accepted"] and not r["correct"] for r in rows),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bench.run_bench")
    ap.add_argument("--mock", action="store_true", help="offline stand-in model (tests the harness)")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--tasks", help="comma-separated task ids, e.g. t01,t06")
    ap.add_argument("--out", help="write full results as JSON")
    a = ap.parse_args(argv)

    db = load(ROOT / "bench" / "db.json")
    tasks = load(ROOT / "bench" / "tasks.json")
    if a.tasks:
        keep = set(a.tasks.split(","))
        tasks = [t for t in tasks if t["id"] in keep]
    if a.mock:
        from .mock import MockModel
        model, label = MockModel(), "mock (scripted slips, says nothing about real models)"
    else:
        from .model import AnthropicModel
        model, label = AnthropicModel(a.model), a.model

    rows = run_bench(model, tasks, db, a.max_attempts)
    print(f"model: {label}   max attempts: {a.max_attempts}\n")
    print(f"{'task':<20}{'attempts':>9}  {'accepted':<9}{'correct':<8}")
    for r in rows:
        print(f"{r['name']:<20}{r['attempts']:>9}  {str(r['accepted']):<9}{str(r['correct']):<8}")
        for f in r["failures"][:2]:
            print(f"    case failed: {json.dumps(f)}")
    s = summarize(rows)
    print(f"\nfirst-try accepted : {s['first_try_accepted']}/{s['tasks']}")
    print(f"accepted in budget : {s['accepted_in_budget']}/{s['tasks']}")
    print(f"correct            : {s['correct']}/{s['tasks']}")
    print(f"incorrect-but-accepted: {s['incorrect_but_accepted']}   <- the number the paper cares about")
    if a.out:
        Path(a.out).write_text(json.dumps({"model": label, "summary": s, "rows": rows}, indent=2),
                               encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
