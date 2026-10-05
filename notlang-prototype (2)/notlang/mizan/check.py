"""Stages 1-4 of the pipeline: shape, types, effects, declared errors."""
from collections import namedtuple

from .errors import MizanError, suggest
from .ops import ERROR_NAME, OPS, SCALARS, base, known_type, unknown_type

VERSIONS = ("0.1", "0.2")
TOP_REQUIRED = ("mizan", "params", "returns", "effects", "nodes", "out")
TOP_OPTIONAL = ("label", "pre", "post", "raises", "context", "scenarios")
V02_KEYS = ("raises", "context", "scenarios")

Checked = namedtuple("Checked", "types order effects raises")


class Env:
    def __init__(self, params, returns, schema, types=None, contexts=None, context=None):
        self.params, self.returns, self.schema = params, returns, schema
        self.types = types or {}
        self.contexts = contexts or {}
        self.context = context


def _err(code, msg, **detail):
    return MizanError("shape", code, msg, detail=detail)


def _validate_scenarios(graph):
    scs = graph.get("scenarios", [])
    if not isinstance(scs, list):
        raise _err("BAD_SCENARIO", "scenarios must be a list")
    for i, s in enumerate(scs):
        if not isinstance(s, dict):
            raise _err("BAD_SCENARIO", "a scenario is an object", index=i)
        extra = set(s) - {"title", "given", "when", "then"}
        missing = {"title", "when", "then"} - set(s)
        if extra or missing:
            raise _err("BAD_SCENARIO", "scenario keys are title, given?, when, then",
                       index=i, extra=sorted(extra), missing=sorted(missing))
        if not isinstance(s["title"], str) or not s["title"].strip():
            raise _err("BAD_SCENARIO", "scenario needs a non-empty title", index=i)
        if not isinstance(s["when"], dict):
            raise _err("BAD_SCENARIO", "'when' maps parameter names to values", index=i)
        if "given" in s and not (isinstance(s["given"], dict)
                                 and all(isinstance(v, list) for v in s["given"].values())):
            raise _err("BAD_SCENARIO", "'given' maps table names to lists of rows", index=i)
        then = s["then"]
        if not isinstance(then, dict) or set(then) - {"result", "error", "prints"} \
                or sum(k in then for k in ("result", "error")) != 1:
            raise _err("BAD_SCENARIO", "'then' needs exactly one of result/error (and optional prints)",
                       index=i)
        if "prints" in then and not (isinstance(then["prints"], list)
                                     and all(isinstance(p, str) for p in then["prints"])):
            raise _err("BAD_SCENARIO", "'prints' is a list of strings", index=i)


def structure(graph):
    """Validate the shape of the graph and return a topological node order."""
    if not isinstance(graph, dict):
        raise _err("NOT_OBJECT", "a Mizan program must be a JSON object")
    for k in TOP_REQUIRED:
        if k not in graph:
            raise _err("MISSING_KEY", f"missing key '{k}'", key=k)
    for k in graph:
        if k not in TOP_REQUIRED + TOP_OPTIONAL:
            raise _err("UNKNOWN_KEY", f"unknown key '{k}'", key=k,
                       did_you_mean=suggest(k, TOP_REQUIRED + TOP_OPTIONAL))
    ver = graph["mizan"]
    if ver not in VERSIONS:
        raise _err("VERSION", f"this interpreter speaks Mizan {', '.join(VERSIONS)}", got=ver)
    if ver == "0.1":
        for k in V02_KEYS:
            if k in graph:
                raise _err("NEEDS_V02", f"'{k}' needs \"mizan\": \"0.2\"", key=k)

    params = graph["params"]
    if not isinstance(params, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                              for k, v in params.items()):
        raise _err("BAD_PARAMS", "params must map names to type names")
    if not isinstance(graph["returns"], str):
        raise _err("BAD_RETURNS", "returns must be a type name")

    fx = graph["effects"]
    if not isinstance(fx, list) or len(set(map(str, fx))) != len(fx):
        raise _err("BAD_EFFECTS", "effects must be a list without duplicates")
    from .ops import EFFECTS
    for e in fx:
        if e not in EFFECTS:
            raise _err("UNKNOWN_EFFECT", f"unknown effect '{e}'", known=list(EFFECTS))

    raises = graph.get("raises", [])
    if not isinstance(raises, list) or len(set(map(str, raises))) != len(raises):
        raise _err("BAD_RAISES", "raises must be a list of unique error names")
    for name in raises:
        if not isinstance(name, str) or not ERROR_NAME.fullmatch(name):
            raise _err("BAD_ERROR_NAME", f"error names are PascalCase, got {name!r}")
    if "context" in graph and not isinstance(graph["context"], str):
        raise _err("BAD_CONTEXT", "context must be a string")
    _validate_scenarios(graph)

    nodes = graph["nodes"]
    if not isinstance(nodes, dict) or not nodes:
        raise _err("BAD_NODES", "nodes must be a non-empty object")
    for nid, n in nodes.items():
        if not isinstance(n, dict) or "op" not in n:
            raise MizanError("shape", "BAD_NODE", "a node is an object with an 'op'", node=nid)
        spec = OPS.get(n["op"])
        if spec is None:
            raise MizanError("shape", "UNKNOWN_OP", f"unknown op {n['op']!r}", node=nid,
                             detail={"known": sorted(OPS), "did_you_mean": suggest(n["op"], OPS)})
        if ver == "0.1" and (spec["since"] != "0.1" or "why" in n):
            raise MizanError("shape", "NEEDS_V02", "this op/key needs \"mizan\": \"0.2\"", node=nid)
        extra = set(n) - {"op", "in", "why", *spec["attrs"]}
        if extra:
            raise MizanError("shape", "UNKNOWN_KEY", f"unexpected keys {sorted(extra)}", node=nid)
        if "why" in n and not isinstance(n["why"], str):
            raise MizanError("shape", "BAD_NODE", "'why' must be a string", node=nid)
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


def _validate_domain(env):
    for alias, b in env.types.items():
        if not (isinstance(alias, str) and ERROR_NAME.fullmatch(alias)) \
                or alias in SCALARS or b not in SCALARS:
            raise MizanError("type", "BAD_DOMAIN",
                             f"domain type {alias!r} must be a PascalCase name mapped to one of {list(SCALARS)}")
    for table, fields in env.schema.items():
        for f, t in fields.items():
            if not known_type(t, env):
                e = unknown_type(t, env)
                e.detail["where"] = f"{table}.{f}"
                raise e
    for ctx, tables in env.contexts.items():
        for t in tables:
            if t not in env.schema:
                raise MizanError("type", "BAD_DOMAIN",
                                 f"context '{ctx}' lists unknown table '{t}'",
                                 detail={"tables": sorted(env.schema), "did_you_mean": suggest(t, env.schema)})


def check(graph, schema=None, domain=None):
    order = structure(graph)
    nodes = graph["nodes"]
    domain = domain or {}
    env = Env(graph["params"], graph["returns"], schema or {}, domain.get("types"),
              domain.get("contexts"), graph.get("context"))
    _validate_domain(env)

    for name, t in graph["params"].items():
        if not known_type(t, env):
            e = unknown_type(t, env)
            e.detail["where"] = f"param {name}"
            raise e
    if not known_type(graph["returns"], env):
        e = unknown_type(graph["returns"], env)
        e.detail["where"] = "returns"
        raise e
    if env.context is not None and env.context not in env.contexts:
        raise MizanError("type", "UNKNOWN_CONTEXT", f"unknown bounded context '{env.context}'",
                         detail={"contexts": sorted(env.contexts),
                                 "did_you_mean": suggest(env.context, env.contexts)})

    types, uses_result, raised = {}, {}, {}
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
        if n["op"] == "fail":
            raised[nid] = {n["error"]}
        elif n["op"] == "try":
            body, fallback = ins
            if n["catch"] not in raised[body]:
                raise MizanError("type", "CATCH_UNREACHABLE",
                                 f"the body of this 'try' cannot raise '{n['catch']}'", node=nid,
                                 detail={"catch": n["catch"], "body_raises": sorted(raised[body])})
            raised[nid] = (raised[body] - {n["catch"]}) | raised[fallback]
        else:
            raised[nid] = set().union(*[raised[r] for r in ins])

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

    used_raises = set().union(*[raised[r] for r in roots])
    declared_raises = set(graph.get("raises", []))
    if used_raises - declared_raises:
        raise MizanError("effect", "RAISES_UNDECLARED",
                         f"function can raise undeclared errors {sorted(used_raises - declared_raises)}",
                         detail={"can_raise": sorted(used_raises), "declared": sorted(declared_raises)})
    if declared_raises - used_raises:
        raise MizanError("effect", "RAISES_UNUSED",
                         f"declared errors that nothing raises: {sorted(declared_raises - used_raises)}",
                         detail={"can_raise": sorted(used_raises), "declared": sorted(declared_raises)})
    return Checked(types, order, used, used_raises)
