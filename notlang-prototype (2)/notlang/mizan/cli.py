"""python -m mizan {check,run,view,hash,test,spec,mutate,lint,gate,subst} FILE ..."""
import argparse
import json
import os

from . import check, fn_hash, run, short_hash, structure, view
from .errors import MizanError, jsonable
from .rules import (format_gate, format_lint, gate, lint, load_policy, substitutable)
from .scenarios import (format_mutation, format_tests, mutation_test, run_scenarios, to_gherkin)


def _load(path):
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            raise MizanError("shape", "BAD_JSON", str(e), detail={"file": path})


def _coerce(ptype, text):
    if ptype == "Int":
        try:
            return int(text)
        except ValueError:
            raise MizanError("args", "BAD_ARGS", f"'{text}' is not an Int")
    if ptype == "Bool":
        if text.lower() not in ("true", "false"):
            raise MizanError("args", "BAD_ARGS", f"'{text}' is not true/false")
        return text.lower() == "true"
    return text  # Money and Str stay strings; the interpreter validates them


def _args(graph, pairs, types):
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise MizanError("args", "BAD_ARGS", f"use --arg name=value, got '{p}'")
        k, v = p.split("=", 1)
        if k not in graph["params"]:
            raise MizanError("args", "BAD_ARGS", f"no parameter '{k}'",
                             detail={"params": graph["params"]})
        ptype = graph["params"][k]
        out[k] = _coerce(types.get(ptype, ptype), v)
    return out


def _grants(items):
    return {g.strip() for item in items or [] for g in item.split(",") if g.strip()}


def _policy(a):
    path = getattr(a, "policy", None) or ("mizan.rules.json" if os.path.exists("mizan.rules.json") else None)
    return load_policy(path)


def main(argv=None):
    p = argparse.ArgumentParser(prog="mizan", description="Mizan reference interpreter and quality toolchain")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "run", "view", "hash", "test", "spec", "mutate", "lint", "gate"):
        s = sub.add_parser(name)
        s.add_argument("file")
        s.add_argument("--db", help="JSON file with {schema, tables, domain}")
        if name == "run":
            s.add_argument("--arg", action="append", help="name=value (repeatable)")
            s.add_argument("--grant", action="append", help="effects to grant, e.g. db.read")
        if name in ("lint", "gate"):
            s.add_argument("--policy", help="rules file (default: ./mizan.rules.json if present)")
        if name == "gate":
            s.add_argument("--json", action="store_true", help="machine-readable report")
    s = sub.add_parser("subst", help="Liskov check: can REPLACEMENT stand in for ORIGINAL?")
    s.add_argument("original")
    s.add_argument("replacement")
    s.add_argument("--db")
    a = p.parse_args(argv)

    try:
        db = _load(a.db) if getattr(a, "db", None) else {}
        domain = db.get("domain") or {}
        types = domain.get("types", {}) or {}
        if a.cmd == "subst":
            orig, repl = _load(a.original), _load(a.replacement)
            structure(orig)
            structure(repl)
            ok, reasons = substitutable(orig, repl)
            print(json.dumps({"substitutable": ok, "reasons": reasons}, indent=2))
            return 0 if ok else 1

        graph = _load(a.file)
        if a.cmd == "view":
            structure(graph)
            print(view(graph, types))
        elif a.cmd == "hash":
            structure(graph)
            print("#" + short_hash(graph, types), fn_hash(graph, types))
        elif a.cmd == "check":
            c = check(graph, db.get("schema", {}), domain)
            print(json.dumps({"ok": True, "hash": "#" + short_hash(graph, types),
                              "effects": sorted(c.effects), "raises": sorted(c.raises)}, indent=2))
        elif a.cmd == "run":
            r = run(graph, _args(graph, a.arg, types), db, _grants(a.grant))
            print(json.dumps(jsonable({"ok": True, "result": r.value, "hash": r.hash,
                                       "effects": r.effects, "printed": r.printed}), indent=2))
        elif a.cmd == "spec":
            structure(graph)
            print(to_gherkin(graph))
        elif a.cmd == "test":
            check(graph, db.get("schema", {}), domain)
            results = run_scenarios(graph, db)
            print(format_tests(graph, results))
            return 0 if results and all(r["passed"] for r in results) else 1
        elif a.cmd == "mutate":
            check(graph, db.get("schema", {}), domain)
            results = run_scenarios(graph, db)
            if not results or not all(r["passed"] for r in results):
                print(format_tests(graph, results))
                print("mutation testing needs green scenarios first")
                return 1
            m = mutation_test(graph, db)
            print(format_mutation(graph, m))
            return 0 if not m["survivors"] else 1
        elif a.cmd == "lint":
            structure(graph)
            v = lint(graph, db, _policy(a))
            print(format_lint(graph, v))
            return 0 if not v else 1
        elif a.cmd == "gate":
            report = gate(graph, db, _policy(a))
            print(json.dumps(jsonable(report), indent=2) if a.json else format_gate(report))
            return 0 if report["ok"] else 1
    except MizanError as e:
        print(json.dumps({"ok": False, "error": e.to_dict()}, indent=2))
        return 1
    return 0
