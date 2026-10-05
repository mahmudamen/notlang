"""The quality rules: Clean Code, SOLID, DDD, TDD/BDD as checks the toolchain enforces.

Humans do not read the code, so the rules cannot live in a style guide. They live here.
"""
import json
import re
from decimal import Decimal

from .check import check, reachable
from .errors import MizanError
from .hashing import contract_hashes, node_hashes
from .scenarios import (contract_coverage, format_mutation, mutation_test, run_scenarios)

DEFAULT_POLICY = {
    "min_scenarios": 3,                  # BDD: behaviour is specified by examples
    "mutation_score_min": 0.8,           # TDD: the tests must be able to fail
    "require_contract_coverage": True,   # TDD: every contract is exercised
    "require_contract": True,            # Design by Contract: say what must hold
    "max_nodes": 30,                     # SOLID-S: one function, one job
    "max_depth": 8,                      # Clean Code: shallow expressions
    "max_params": 3,                     # Clean Code / SOLID-I: narrow interfaces
    "min_duplicate_size": 3,             # Clean Code: DRY (nodes in the repeated subgraph)
    "no_dead_nodes": True,               # Clean Code: no dead code
    "no_duplicate_subgraphs": True,
    "no_unused_params": True,            # SOLID-I: do not ask for what you do not use
    "magic_consts_need_why": True,       # Clean Code: no magic numbers
    "snake_case_names": True,            # Clean Code: naming
    "require_label": True,
    "require_context": True,             # DDD: bounded context
    "require_glossary": True,            # DDD: ubiquitous language
    "forbidden_effect_mixes": [["db.read", "io.print"]],   # SOLID-S (CQS): do not mix concerns
}

SNAKE = re.compile(r"[a-z][a-z0-9_]*")


def load_policy(path=None):
    policy = dict(DEFAULT_POLICY)
    if path:
        with open(path, encoding="utf-8") as f:
            policy.update(json.load(f))
    return policy


def _depth(graph, nid, memo):
    if nid not in memo:
        ins = graph["nodes"][nid].get("in", [])
        memo[nid] = 1 + max((_depth(graph, r, memo) for r in ins), default=0)
    return memo[nid]


def lint(graph, db, policy):
    """Static rules. Returns a list of {rule, principle, message, node}."""
    out = []
    nodes = graph["nodes"]
    domain = db.get("domain") or {}
    types = domain.get("types", {}) or {}
    roots = [graph["out"], *graph.get("pre", []), *graph.get("post", [])]
    live = reachable(graph, roots)

    def add(rule, principle, message, node=None):
        out.append({"rule": rule, "principle": principle, "message": message, "node": node})

    if len(nodes) > policy["max_nodes"]:
        add("max_nodes", "SOLID-S", f"{len(nodes)} nodes (max {policy['max_nodes']}): split the function")
    memo = {}
    depth = max(_depth(graph, r, memo) for r in roots)
    if depth > policy["max_depth"]:
        add("max_depth", "Clean Code", f"expression depth {depth} (max {policy['max_depth']})")
    if len(graph["params"]) > policy["max_params"]:
        add("max_params", "Clean Code", f"{len(graph['params'])} params (max {policy['max_params']})")

    if policy["no_dead_nodes"]:
        for nid in nodes:
            if nid not in live:
                add("no_dead_nodes", "Clean Code", f"node '{nid}' is never used: delete it", nid)

    if policy["no_duplicate_subgraphs"]:
        hashes = node_hashes(graph, types)
        groups = {}
        for nid in live:
            groups.setdefault(hashes[nid], []).append(nid)
        sized = []
        for members in groups.values():
            if len(members) > 1:
                size = len(reachable(graph, [members[0]]))
                if size >= policy["min_duplicate_size"]:
                    sized.append((size, sorted(members)))
        covered = set()
        for size, members in sorted(sized, key=lambda x: (-x[0], x[1])):
            if all(m in covered for m in members):
                continue
            add("no_duplicate_subgraphs", "Clean Code (DRY)",
                f"nodes {members} compute the same {size}-node expression: share one node", members[0])
            for m in members:
                covered |= reachable(graph, [m])

    if policy["no_unused_params"]:
        used = {nodes[n]["name"] for n in live if nodes[n]["op"] == "param"}
        for p in graph["params"]:
            if p not in used:
                add("no_unused_params", "SOLID-I", f"param '{p}' is never used: narrow the interface")

    if policy["magic_consts_need_why"]:
        for nid in sorted(live):
            n = nodes[nid]
            if n["op"] != "const" or n.get("why"):
                continue
            t, v = types.get(n["type"], n["type"]), n["value"]
            if t == "Bool" or (t in ("Int", "Money") and Decimal(str(v)) in (0, 1)):
                continue
            add("magic_consts_need_why", "Clean Code", f"const {v!r} needs a 'why' (no magic values)", nid)

    if policy["snake_case_names"]:
        names = list(graph["params"]) + ([graph["label"]] if graph.get("label") else [])
        for name in names:
            if not SNAKE.fullmatch(name):
                add("snake_case_names", "Clean Code", f"'{name}' is not snake_case")
    if policy["require_label"] and not graph.get("label"):
        add("require_label", "Clean Code", "a function needs a label (a name that says what it does)")

    if policy["require_contract"] and graph["params"] and not graph.get("pre") and not graph.get("post"):
        add("require_contract", "Design by Contract", "no pre or post condition: say what must hold")

    if policy["require_context"] and domain.get("contexts") and not graph.get("context"):
        add("require_context", "DDD", "declare the bounded context this function lives in")

    if policy["require_glossary"] and types:
        glossary = domain.get("glossary", {})
        used_types = set(graph["params"].values()) | {graph["returns"]}
        for n in (nodes[x] for x in live):
            used_types |= {n[k] for k in ("type", "as") if isinstance(n.get(k), str)}
            if n["op"] == "db.scan":
                used_types |= set(db.get("schema", {}).get(n["table"], {}).values())
        for t in sorted(used_types & set(types)):
            if not str(glossary.get(t, "")).strip():
                add("require_glossary", "DDD (ubiquitous language)",
                    f"domain type '{t}' has no glossary entry")

    for mix in policy["forbidden_effect_mixes"]:
        if set(mix) <= set(graph["effects"]):
            add("forbidden_effect_mixes", "SOLID-S (CQS)",
                f"mixes effects {mix}: split into two functions")
    return out


def format_lint(graph, violations):
    if not violations:
        return f"LINT  {graph.get('label', 'function')}: clean"
    lines = [f"LINT  {graph.get('label', 'function')}: {len(violations)} violation(s)"]
    for v in violations:
        where = f" [{v['node']}]" if v["node"] else ""
        lines.append(f"  [{v['principle']}] {v['rule']}{where}: {v['message']}")
    return "\n".join(lines)


def substitutable(a, b):
    """Liskov check (a sufficient, syntactic one): can function b stand in for function a?

    b must accept at least what a accepts (no stronger precondition), promise at least what a
    promises (no weaker postcondition), and not use more effects or raise more errors.
    """
    reasons = []

    def no(rule, message):
        reasons.append({"rule": rule, "message": message})

    if a["params"] != b["params"]:
        no("signature", f"params differ: {a['params']} vs {b['params']}")
    if a["returns"] != b["returns"]:
        no("signature", f"return type differs: {a['returns']} vs {b['returns']}")
    if set(b["effects"]) - set(a["effects"]):
        no("effects", f"replacement uses extra effects {sorted(set(b['effects']) - set(a['effects']))}")
    if set(b.get("raises", [])) - set(a.get("raises", [])):
        no("raises", f"replacement can raise new errors "
                     f"{sorted(set(b.get('raises', [])) - set(a.get('raises', [])))}")
    ha, hb = contract_hashes(a), contract_hashes(b)
    if set(hb["pre"]) - set(ha["pre"]):
        no("pre", "replacement demands more than the original (stronger precondition)")
    if set(ha["post"]) - set(hb["post"]):
        no("post", "replacement promises less than the original (dropped postcondition)")
    return (not reasons), reasons


def gate(graph, db, policy):
    """The quality gate: compile + tests + mutation + coverage + lint. Nothing ships without it."""
    schema, domain = db.get("schema", {}), db.get("domain", {})
    report = {"label": graph.get("label"), "ok": False}
    try:
        check(graph, schema, domain)
    except MizanError as e:
        report["compile"] = {"ok": False, "error": e.to_dict()}
        return report
    report["compile"] = {"ok": True}

    results = run_scenarios(graph, db)
    green = sum(r["passed"] for r in results)
    report["tests"] = {"ok": green == len(results) and len(results) >= policy["min_scenarios"],
                       "green": green, "total": len(results), "min": policy["min_scenarios"],
                       "failures": [r for r in results if not r["passed"]]}

    if results and green == len(results):
        mut = mutation_test(graph, db)
        report["mutation"] = {"ok": mut["score"] >= policy["mutation_score_min"], **{
            k: mut[k] for k in ("total", "killed", "survivors", "score")},
            "min": policy["mutation_score_min"]}
        uncovered = contract_coverage(graph, results, mut)
        report["coverage"] = {"ok": not (policy["require_contract_coverage"] and uncovered),
                              "uncovered": uncovered}
    else:
        report["mutation"] = {"ok": False, "skipped": "scenarios are missing or red"}
        report["coverage"] = {"ok": False, "skipped": "scenarios are missing or red"}

    violations = lint(graph, db, policy)
    report["lint"] = {"ok": not violations, "violations": violations}
    report["ok"] = all(report[k]["ok"] for k in ("compile", "tests", "mutation", "coverage", "lint"))
    return report


def format_gate(report):
    name = report.get("label") or "function"
    lines = [f"GATE  {name}"]
    c = report["compile"]
    if not c["ok"]:
        e = c["error"]
        lines.append(f"  compile   FAIL  [{e['stage']}/{e['code']}] {e['message']}")
        if e.get("hint"):
            lines.append(f"            hint: {e['hint']}")
        lines.append("RESULT: FAIL")
        return "\n".join(lines)
    lines.append("  compile   ok")
    t = report["tests"]
    lines.append(f"  tests     {'ok  ' if t['ok'] else 'FAIL'}  {t['green']}/{t['total']} green (min {t['min']} scenarios)")
    for f in t["failures"]:
        lines.append(f"            - {f['title']}: {f['message']}")
    m = report["mutation"]
    if "skipped" in m:
        lines.append(f"  mutation  FAIL  skipped: {m['skipped']}")
    else:
        verdict = "no survivors, nice" if not m["survivors"] else "a scenario is missing"
        lines.append(f"  mutation  {'ok  ' if m['ok'] else 'FAIL'}  killed {m['killed']}/{m['total']} "
                     f"({m['score']:.0%}, min {m['min']:.0%}) {verdict}")
        for s in m["survivors"]:
            lines.append(f"            - survivor: {s}")
    cv = report["coverage"]
    if "skipped" in cv:
        lines.append(f"  coverage  FAIL  skipped: {cv['skipped']}")
    elif cv["uncovered"]:
        lines.append(f"  coverage  {'ok  ' if cv['ok'] else 'FAIL'}  never exercised: {', '.join(cv['uncovered'])}")
    else:
        lines.append("  coverage  ok    every contract is exercised")
    l = report["lint"]
    lines.append(f"  lint      {'ok  ' if l['ok'] else 'FAIL'}  {len(l['violations'])} violation(s)")
    for v in l["violations"]:
        where = f" [{v['node']}]" if v["node"] else ""
        lines.append(f"            - [{v['principle']}] {v['rule']}{where}: {v['message']}")
    lines.append("RESULT: " + ("PASS" if report["ok"] else "FAIL"))
    return "\n".join(lines)
