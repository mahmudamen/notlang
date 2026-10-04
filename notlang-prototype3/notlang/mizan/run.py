"""Stage 5-6: bind args, check effect grants, run with contracts."""
from collections import namedtuple

from .check import check
from .errors import MizanError
from .hashing import short_hash
from .ops import OPS, parse_value
from .view import render_node

Result = namedtuple("Result", "value hash effects printed")


class Ctx:
    def __init__(self, args, tables, types):
        self.args, self.tables, self.types = args, tables, types
        self.result = None
        self.printed = []


def load_tables(schema, tables):
    out = {}
    for name, fields in schema.items():
        rows = []
        for i, row in enumerate(tables.get(name, [])):
            if set(row) != set(fields):
                raise MizanError("runtime", "DB_ROW_INVALID",
                                 f"row {i} of '{name}' does not match the schema",
                                 detail={"expected": sorted(fields), "got": sorted(row)})
            rows.append({f: parse_value(t, row[f], stage="runtime") for f, t in fields.items()})
        out[name] = rows
    return out


def bind_args(params, args):
    if set(args) != set(params):
        raise MizanError("args", "BAD_ARGS", "arguments must match params exactly",
                         detail={"expected": params, "got": sorted(args)})
    return {k: parse_value(params[k], args[k], stage="args") for k in params}


def run(graph, args, db=None, granted=()):
    db = db or {}
    schema = db.get("schema", {})
    checked = check(graph, schema)

    denied = set(graph["effects"]) - set(granted)
    if denied:
        raise MizanError("effect", "EFFECT_DENIED", f"effects not granted: {sorted(denied)}",
                         detail={"requested": sorted(graph["effects"]), "granted": sorted(granted)})

    bound = bind_args(graph["params"], args)
    ctx = Ctx(bound, load_tables(schema, db.get("tables", {})), checked.types)
    nodes, memo = graph["nodes"], {}

    def ev(nid):
        if nid not in memo:
            n = nodes[nid]
            memo[nid] = OPS[n["op"]]["eval"](
                n, lambda i: ev(n["in"][i]), ctx, checked.types[nid])
        return memo[nid]

    def contract(kind, i, nid):
        if not ev(nid):
            raise MizanError("contract", f"{kind.upper()}_FAILED",
                             f"{kind}[{i}] failed: {render_node(graph, nid)}", node=nid,
                             detail={"expr": render_node(graph, nid), "args": bound,
                                     "result": ctx.result})

    for i, nid in enumerate(graph.get("pre", [])):
        contract("pre", i, nid)
    ctx.result = ev(graph["out"])
    for i, nid in enumerate(graph.get("post", [])):
        contract("post", i, nid)
    return Result(ctx.result, "#" + short_hash(graph), sorted(checked.effects), ctx.printed)
