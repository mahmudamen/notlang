"""python -m mizan {check,run,view,hash} FILE ..."""
import argparse
import json

from . import check, fn_hash, run, short_hash, structure, view
from .errors import MizanError, jsonable


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


def _args(graph, pairs):
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise MizanError("args", "BAD_ARGS", f"use --arg name=value, got '{p}'")
        k, v = p.split("=", 1)
        if k not in graph["params"]:
            raise MizanError("args", "BAD_ARGS", f"no parameter '{k}'",
                             detail={"params": graph["params"]})
        out[k] = _coerce(graph["params"][k], v)
    return out


def _grants(items):
    return {g.strip() for item in items or [] for g in item.split(",") if g.strip()}


def main(argv=None):
    p = argparse.ArgumentParser(prog="mizan", description="Mizan v0.1 reference interpreter")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "run", "view", "hash"):
        s = sub.add_parser(name)
        s.add_argument("file")
        if name in ("check", "run"):
            s.add_argument("--db", help="JSON file with {schema, tables}")
        if name == "run":
            s.add_argument("--arg", action="append", help="name=value (repeatable)")
            s.add_argument("--grant", action="append", help="effects to grant, e.g. db.read")
    a = p.parse_args(argv)

    try:
        graph = _load(a.file)
        db = _load(a.db) if getattr(a, "db", None) else {}
        if a.cmd == "view":
            structure(graph)
            print(view(graph))
        elif a.cmd == "hash":
            structure(graph)
            print("#" + short_hash(graph), fn_hash(graph))
        elif a.cmd == "check":
            c = check(graph, db.get("schema", {}))
            print(json.dumps({"ok": True, "hash": "#" + short_hash(graph),
                              "effects": sorted(c.effects)}, indent=2))
        else:
            r = run(graph, _args(graph, a.arg), db, _grants(a.grant))
            print(json.dumps(jsonable({"ok": True, "result": r.value, "hash": r.hash,
                                       "effects": r.effects, "printed": r.printed}), indent=2))
    except MizanError as e:
        print(json.dumps({"ok": False, "error": e.to_dict()}, indent=2))
        return 1
    return 0
