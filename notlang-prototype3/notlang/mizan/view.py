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
        v = n["value"]
        if n["type"] == "Money":
            return f"{v}m"
        if n["type"] == "Bool":
            return "true" if v else "false"
        return repr(v) if n["type"] == "Str" else str(v)
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
    return f"<{op}>"


def view(graph):
    head = f"fn #{short_hash(graph)}"
    if graph.get("label"):
        head += f"  ({graph['label']})"
    lines = [head]
    params = ", ".join(f"{k}: {v}" for k, v in graph["params"].items()) or "-"
    lines.append(f"  in:   {params}")
    lines.append(f"  out:  {graph['returns']}")
    lines.append(f"  fx:   [{', '.join(graph['effects'])}]")
    for nid in graph.get("pre", []):
        lines.append(f"  pre:  {render_node(graph, nid)}")
    for nid in graph.get("post", []):
        lines.append(f"  post: {render_node(graph, nid)}")
    lines.append(f"  body: {render_node(graph, graph['out'])}")
    return "\n".join(lines)
