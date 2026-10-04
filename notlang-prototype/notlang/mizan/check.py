"""Stages 1-4 of the pipeline: shape, types, effects (contracts are run later)."""
from collections import namedtuple

from .errors import MizanError
from .ops import EFFECTS, OPS, SCALARS, is_scalar_type

TOP_REQUIRED = ("mizan", "params", "returns", "effects", "nodes", "out")
TOP_OPTIONAL = ("label", "pre", "post")

Checked = namedtuple("Checked", "types order effects")


class Env:
    def __init__(self, params, returns, schema):
        self.params, self.returns, self.schema = params, returns, schema


def _err(code, msg, **detail):
    return MizanError("shape", code, msg, detail=detail)


def structure(graph):
    """Validate the shape of the graph and return a topological node order."""
    if not isinstance(graph, dict):
        raise _err("NOT_OBJECT", "a Mizan program must be a JSON object")
    for k in TOP_REQUIRED:
        if k not in graph:
            raise _err("MISSING_KEY", f"missing key '{k}'", key=k)
    for k in graph:
        if k not in TOP_REQUIRED + TOP_OPTIONAL:
            raise _err("UNKNOWN_KEY", f"unknown key '{k}'", key=k)
    if graph["mizan"] != "0.1":
        raise _err("VERSION", "this interpreter speaks Mizan 0.1", got=graph["mizan"])

    params = graph["params"]
    if not isinstance(params, dict) or not all(isinstance(k, str) and is_scalar_type(v)
                                              for k, v in params.items()):
        raise _err("BAD_PARAMS", f"params must map names to one of {list(SCALARS)}")
    if not is_scalar_type(graph["returns"]):
        raise _err("BAD_RETURNS", f"returns must be one of {list(SCALARS)}")

    fx = graph["effects"]
    if not isinstance(fx, list) or len(set(map(str, fx))) != len(fx):
        raise _err("BAD_EFFECTS", "effects must be a list without duplicates")
    for e in fx:
        if e not in EFFECTS:
            raise _err("UNKNOWN_EFFECT", f"unknown effect '{e}'", known=list(EFFECTS))

    nodes = graph["nodes"]
    if not isinstance(nodes, dict) or not nodes:
        raise _err("BAD_NODES", "nodes must be a non-empty object")
    for nid, n in nodes.items():
        if not isinstance(n, dict) or "op" not in n:
            raise MizanError("shape", "BAD_NODE", "a node is an object with an 'op'", node=nid)
        spec = OPS.get(n["op"])
        if spec is None:
            raise MizanError("shape", "UNKNOWN_OP", f"unknown op '{n['op']}'", node=nid,
                             detail={"known": sorted(OPS)})
        extra = set(n) - {"op", "in", *spec["attrs"]}
        if extra:
            raise MizanError("shape", "UNKNOWN_KEY", f"unexpected keys {sorted(extra)}", node=nid)
        missing = [a for a in spec["attrs"] if a not in n]
        if missing:
            raise MizanError("shape", "MISSING_ATTR", f"op '{n['op']}' needs {missing}", node=nid)
        ins = n.get("in", [])
        if not isinstance(ins, list) or len(ins) != spec["arity"]:
            raise MizanError("shape", "ARITY", f"op '{n['op']}' takes {spec['arity']} input(s)",
                             node=nid, detail={"got": len(ins) if isinstance(ins, list) else None})
        for r in ins:
            if r not in nodes:
                raise MizanError("shape", "UNKNOWN_REF", f"input '{r}' is not a node", node=nid)

    if graph["out"] not in nodes:
        raise _err("UNKNOWN_REF", "'out' points to an unknown node", ref=graph["out"])
    for key in ("pre", "post"):
        lst = graph.get(key, [])
        if not isinstance(lst, list) or any(r not in nodes for r in lst):
            raise _err("UNKNOWN_REF", f"'{key}' must be a list of node ids")

    order, state = [], {}

    def visit(nid):
        s = state.get(nid)
        if s == 2:
            return
        if s == 1:
            raise MizanError("shape", "CYCLE", f"cycle through node '{nid}'", node=nid)
        state[nid] = 1
        for r in nodes[nid].get("in", []):
            visit(r)
        state[nid] = 2
        order.append(nid)

    for nid in nodes:
        visit(nid)
    return order


def reachable(graph, roots):
    seen, stack = set(), list(roots)
    while stack:
        nid = stack.pop()
        if nid not in seen:
            seen.add(nid)
            stack.extend(graph["nodes"][nid].get("in", []))
    return seen


def check(graph, schema=None):
    order = structure(graph)
    nodes = graph["nodes"]
    env = Env(graph["params"], graph["returns"], schema or {})
    types, uses_result = {}, {}

    for nid in order:
        n = nodes[nid]
        ins = n.get("in", [])
        try:
            types[nid] = OPS[n["op"]]["check"](n, [types[r] for r in ins], env)
        except MizanError as e:
            if e.node is None:
                e.node = nid
            raise
        uses_result[nid] = n["op"] == "result" or any(uses_result[r] for r in ins)

    out = graph["out"]
    if types[out] != graph["returns"]:
        raise MizanError("type", "RETURN_MISMATCH",
                         f"body has type {types[out]} but the function returns {graph['returns']}",
                         node=out, detail={"body": types[out], "returns": graph["returns"]})
    if uses_result[out]:
        raise MizanError("type", "RESULT_IN_BODY", "the body cannot depend on 'result'", node=out)
    for i, nid in enumerate(graph.get("pre", [])):
        if types[nid] != "Bool":
            raise MizanError("type", "CONTRACT_NOT_BOOL", f"pre[{i}] must be Bool",
                             node=nid, detail={"got": types[nid]})
        if uses_result[nid]:
            raise MizanError("type", "RESULT_IN_PRE", f"pre[{i}] cannot use 'result'", node=nid)
    for i, nid in enumerate(graph.get("post", [])):
        if types[nid] != "Bool":
            raise MizanError("type", "CONTRACT_NOT_BOOL", f"post[{i}] must be Bool",
                             node=nid, detail={"got": types[nid]})

    roots = [out] + list(graph.get("pre", [])) + list(graph.get("post", []))
    used = set()
    for nid in reachable(graph, roots):
        used.update(OPS[nodes[nid]["op"]]["effects"])
    declared = set(graph["effects"])
    if used - declared:
        raise MizanError("effect", "EFFECT_UNDECLARED",
                         f"program uses undeclared effects {sorted(used - declared)}",
                         detail={"used": sorted(used), "declared": sorted(declared)})
    if declared - used:
        raise MizanError("effect", "EFFECT_UNUSED",
                         f"declared but unused effects {sorted(declared - used)} (least privilege)",
                         detail={"used": sorted(used), "declared": sorted(declared)})
    return Checked(types, order, used)
