"""Content addressing: a function's identity is the hash of its meaning.

Node ids, the label and key order do not matter; structure does.
"""
import hashlib
import json
from decimal import Decimal

from .ops import parse_value


def _sha(obj):
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _node_hash(graph, nid, memo):
    if nid in memo:
        return memo[nid]
    n = graph["nodes"][nid]
    attrs = {k: v for k, v in n.items() if k != "in"}
    if n["op"] == "const":
        d = parse_value(n["type"], n["value"])
        attrs["value"] = format(d.normalize(), "f") if isinstance(d, Decimal) else d
    kids = [_node_hash(graph, r, memo) for r in n.get("in", [])]
    memo[nid] = _sha({"a": attrs, "c": kids})
    return memo[nid]


def fn_hash(graph):
    memo = {}

    def h(nid):
        return _node_hash(graph, nid, memo)

    return _sha({
        "params": graph["params"],
        "returns": graph["returns"],
        "effects": sorted(graph["effects"]),
        "pre": sorted(h(n) for n in graph.get("pre", [])),
        "post": sorted(h(n) for n in graph.get("post", [])),
        "out": h(graph["out"]),
    })


def short_hash(graph):
    return fn_hash(graph)[:8]
