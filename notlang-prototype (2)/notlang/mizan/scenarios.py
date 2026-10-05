"""TDD + BDD. Scenarios live inside the program (Given / When / Then).

* run_scenarios   : the red/green runner
* to_gherkin      : living documentation a human can review instead of the code
* mutation_test   : "who tests the tests?" Breaks the program on purpose and checks the
                    scenarios notice. Survivors mean a missing scenario.
* contract_coverage: every contract must be exercised by a scenario or caught a mutant.
"""
import copy
import json
from decimal import Decimal

from .check import check, reachable
from .errors import MizanError
from .hashing import fn_hash
from .ops import parse_value
from .run import run
from .view import render_node

SWAP = {"gt": "ge", "ge": "gt", "lt": "le", "le": "lt", "eq": "ne", "ne": "eq",
        "add": "sub", "sub": "add", "and": "or", "or": "and"}


def _types(db):
    return (db.get("domain") or {}).get("types", {}) or {}


def _scenario_db(sc, db):
    given = sc.get("given")
    if not given:
        return db
    return {**db, "tables": {**db.get("tables", {}), **given}}


def _describe(then):
    return f"failure {then['error']}" if "error" in then else f"result {then['result']}"


def run_scenarios(graph, db):
    """Run every scenario with exactly the effects the function declares."""
    results, granted, types = [], set(graph["effects"]), _types(db)
    for sc in graph.get("scenarios", []):
        then = sc["then"]
        entry = {"title": sc["title"], "passed": False, "message": "", "code": None, "node": None}
        try:
            r = run(graph, sc["when"], _scenario_db(sc, db), granted)
        except MizanError as e:
            entry["code"], entry["node"] = e.code, e.node
            if then.get("error") == e.code:
                entry["passed"] = True
            else:
                entry["message"] = f"expected {_describe(then)} but it failed with {e.code}: {e.message}"
        else:
            if "error" in then:
                entry["message"] = f"expected {_describe(then)} but got result {r.value}"
            else:
                try:
                    expected = parse_value(graph["returns"], then["result"], types=types)
                except MizanError as e:
                    entry["message"] = f"bad expected result: {e.message}"
                else:
                    if r.value != expected:
                        entry["message"] = f"expected {_describe(then)} but got result {r.value}"
                    elif "prints" in then and r.printed != then["prints"]:
                        entry["message"] = f"expected prints {then['prints']} but got {r.printed}"
                    else:
                        entry["passed"] = True
        results.append(entry)
    return results


def format_tests(graph, results):
    green = sum(r["passed"] for r in results)
    lines = [f"TDD  {graph.get('label', 'function')}: {len(results)} scenario(s)"]
    for r in results:
        lines.append(f"  {'ok  ' if r['passed'] else 'FAIL'}  {r['title']}")
        if not r["passed"]:
            lines.append(f"        {r['message']}")
    lines.append(f"{green}/{len(results)} green" + ("" if green == len(results) else "  (RED)"))
    return "\n".join(lines)


def to_gherkin(graph):
    sig = ", ".join(f"{k}: {v}" for k, v in graph["params"].items())
    lines = [f"Feature: {graph.get('label', 'function')}({sig}) -> {graph['returns']}"]
    if graph.get("context"):
        lines.append(f"  Bounded context: {graph['context']}")
    for kind in ("pre", "post"):
        for nid in graph.get(kind, []):
            lines.append(f"  Rule: {kind}  {render_node(graph, nid)}")
    if graph.get("raises"):
        lines.append(f"  Rule: may fail with {', '.join(graph['raises'])}")
    for sc in graph.get("scenarios", []):
        lines += ["", f"  Scenario: {sc['title']}"]
        given = sc.get("given")
        if given:
            for table, rows in given.items():
                lines.append(f"    Given table {table} holds {len(rows)} row(s)")
        else:
            lines.append("    Given the shared test data")
        when = " and ".join(f"{k} = {json.dumps(v)}" for k, v in sc["when"].items())
        lines.append(f"    When {when or 'called with no arguments'}")
        then = sc["then"]
        if "error" in then:
            lines.append(f"    Then it fails with {then['error']}")
        else:
            lines.append(f"    Then the result is {json.dumps(then['result'])}")
        for p in then.get("prints", []):
            lines.append(f"    And it prints {json.dumps(p)}")
    return "\n".join(lines)


def mutants(graph, types):
    live = reachable(graph, [graph["out"], *graph.get("pre", []), *graph.get("post", [])])
    for nid in graph["nodes"]:
        if nid not in live:
            continue
        n = graph["nodes"][nid]
        op = n["op"]
        m = copy.deepcopy(graph)
        mn = m["nodes"][nid]
        if op in SWAP:
            mn["op"] = SWAP[op]
            yield f"{nid}: {op} -> {SWAP[op]}", m
        elif op == "if":
            mn["in"] = [mn["in"][0], mn["in"][2], mn["in"][1]]
            yield f"{nid}: swap the if-branches", m
        elif op == "const":
            t, v = types.get(n["type"], n["type"]), n["value"]
            if t == "Bool":
                nv = not v
            elif t == "Int":
                nv = v + 1
            elif t == "Money":
                nv = str(Decimal(str(v)) + 1)
            else:
                continue
            mn["value"] = nv
            yield f"{nid}: const {v} -> {nv}", m


def mutation_test(graph, db):
    types, schema, domain = _types(db), db.get("schema", {}), db.get("domain", {})
    base_hash = fn_hash(graph, types)
    total, killed, survivors = 0, 0, []
    caught = {"pre": set(), "post": set()}
    for desc, m in mutants(graph, types):
        try:
            check(m, schema, domain)
        except MizanError:
            continue                      # does not compile: not a real mutant
        if fn_hash(m, types) == base_hash:
            continue
        total += 1
        results = run_scenarios(m, db)
        red = [r for r in results if not r["passed"]]
        if not red:
            survivors.append(desc)
            continue
        killed += 1
        for r in red:                     # which contract noticed the bug, if any?
            kind = {"PRE_FAILED": "pre", "POST_FAILED": "post"}.get(r["code"])
            if kind and r["node"] in m.get(kind, []):
                caught[kind].add(m[kind].index(r["node"]))
    return {"total": total, "killed": killed, "survivors": survivors,
            "score": (killed / total) if total else 1.0, "caught": caught}


def contract_coverage(graph, results, mutation):
    covered = {"pre": set(mutation["caught"]["pre"]), "post": set(mutation["caught"]["post"])}
    for r in results:
        kind = {"PRE_FAILED": "pre", "POST_FAILED": "post"}.get(r["code"])
        if kind and r["node"] in graph.get(kind, []):
            covered[kind].add(graph[kind].index(r["node"]))
    return [f"{kind}[{i}]" for kind in ("pre", "post")
            for i in range(len(graph.get(kind, []))) if i not in covered[kind]]


def format_mutation(graph, m):
    lines = [f"MUTATION  {graph.get('label', 'function')}: killed {m['killed']}/{m['total']} "
             f"mutants ({m['score']:.0%})"]
    if m["survivors"]:
        lines.append("survivors (a scenario is missing):")
        lines += [f"  - {s}" for s in m["survivors"]]
    else:
        lines.append("no survivors")
    return "\n".join(lines)
