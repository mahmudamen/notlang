"""The read-only viewer: renders a graph for human audit. Never used to write."""
from .hashing import short_hash

INFIX = {"add": "+", "sub": "-", "mul": "*", "eq": "==", "ne": "!=", "gt": ">",
         "ge": ">=", "lt": "<", "le": "<=", "and": "and", "or": "or"}


def render_node(graph, nid, top=True):
    n = graph["nodes"][nid]
    op, ins = n["op"], n.get("in", [])

    def r(i):
        return render_node(graph, ins[i], top=False)

    if op == "const":
        v, t = n["value"], n["type"]
        if t == "Money":
            return f"{v}m"
        if t == "Bool":
            return "true" if v else "false"
        if t == "Str":
            return repr(v)
        if t == "Int":
            return str(v)
        return f"{v}:{t}"                      # a domain value, e.g. 0:Qty
    if op == "param":
        return n["name"]
    if op == "result":
        return "result"
    if op in INFIX:
        s = f"{r(0)} {INFIX[op]} {r(1)}"
        return s if top else f"({s})"
    if op == "not":
        return f"not {r(0)}"
    if op == "if":
        return f"({r(1)} if {r(0)} else {r(2)})"
    if op == "db.scan":
        return f"db.{n['table']}"
    if op == "filter_eq":
        return f"filter({r(0)}, {n['field']} == {r(1)})"
    if op == "pluck":
        return f"{r(0)}.{n['field']}"
    if op in ("sum", "len"):
        return f"{op}({r(0)})"
    if op == "io.print":
        return f"print({r(0)})"
    if op == "wrap":
        return f"{n['as']}({r(0)})"
    if op == "unwrap":
        return f"{r(0)}.raw"
    if op == "fail":
        return f"fail {n['error']}"
    if op == "try":
        return f"try({r(0)} catch {n['catch']} => {r(1)})"
    return f"<{op}>"


def view(graph, types=None):
    head = f"fn #{short_hash(graph, types)}"
    if graph.get("label"):
        head += f"  ({graph['label']})"
    lines = [head]
    if graph.get("context"):
        lines.append(f"  ctx:  {graph['context']}")
    params = ", ".join(f"{k}: {v}" for k, v in graph["params"].items()) or "-"
    lines.append(f"  in:   {params}")
    lines.append(f"  out:  {graph['returns']}")
    lines.append(f"  fx:   [{', '.join(graph['effects'])}]")
    if graph.get("raises"):
        lines.append(f"  err:  [{', '.join(graph['raises'])}]")
    for nid in graph.get("pre", []):
        lines.append(f"  pre:  {render_node(graph, nid)}")
    for nid in graph.get("post", []):
        lines.append(f"  post: {render_node(graph, nid)}")
    lines.append(f"  body: {render_node(graph, graph['out'])}")
    for nid, n in graph["nodes"].items():
        if n.get("why"):
            lines.append(f"  why:  {render_node(graph, nid)}  -- {n['why']}")
    return "\n".join(lines)
