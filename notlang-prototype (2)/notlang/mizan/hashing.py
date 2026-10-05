"""Content addressing: a function's identity is the hash of its meaning.

Node ids, the label, `why` notes, scenarios and key order do not matter; structure does.
"""
import hashlib
import json
from decimal import Decimal

from .errors import MizanError
from .ops import parse_value

IGNORED_NODE_KEYS = ("in", "why")


def _sha(obj):
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _node_hash(graph, nid, memo, types):
    if nid in memo:
        return memo[nid]
    n = graph["nodes"][nid]
    attrs = {k: v for k, v in n.items() if k not in IGNORED_NODE_KEYS}
    if n["op"] == "const":
        try:
            d = parse_value(n["type"], n["value"], types=types)
            attrs["value"] = format(d.normalize(), "f") if isinstance(d, Decimal) else d
        except MizanError:
            pass  # unknown domain type: hash the literal as written
    kids = [_node_hash(graph, r, memo, types) for r in n.get("in", [])]
    memo[nid] = _sha({"a": attrs, "c": kids})
    return memo[nid]


def node_hashes(graph, types=None):
    memo = {}
    for nid in graph["nodes"]:
        _node_hash(graph, nid, memo, types or {})
    return memo


def contract_hashes(graph, types=None):
    memo = node_hashes(graph, types)
    return {"pre": [memo[n] for n in graph.get("pre", [])],
            "post": [memo[n] for n in graph.get("post", [])]}


def fn_hash(graph, types=None):
    memo = node_hashes(graph, types)
    body = {
        "params": graph["params"],
        "returns": graph["returns"],
        "effects": sorted(graph["effects"]),
        "pre": sorted(memo[n] for n in graph.get("pre", [])),
        "post": sorted(memo[n] for n in graph.get("post", [])),
        "out": memo[graph["out"]],
    }
    if graph.get("raises"):          # only when present, so v0.1 hashes stay stable
        body["raises"] = sorted(graph["raises"])
    return _sha(body)


def short_hash(graph, types=None):
    return fn_hash(graph, types)[:8]
