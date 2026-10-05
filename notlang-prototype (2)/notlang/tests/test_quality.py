import contextlib
import copy
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mizan import (DEFAULT_POLICY, MizanError, check, fn_hash, gate, lint, mutation_test,  # noqa: E402
                   run, run_scenarios, structure, substitutable, to_gherkin)
from mizan.cli import main  # noqa: E402
from mizan.rules import format_gate  # noqa: E402
from mizan.scenarios import contract_coverage  # noqa: E402

EX = ROOT / "examples"


def load(name):
    return json.loads((EX / name).read_text(encoding="utf-8"))


SHOP = load("shop_db.json")
DOMAIN, SCHEMA, TYPES = SHOP["domain"], SHOP["schema"], SHOP["domain"]["types"]
RESERVE = load("reserve_stock.json")
FALLBACK = load("reserve_or_fallback.json")
STRICT = load("reserve_stock_strict.json")
LENIENT = load("reserve_stock_lenient.json")
OLD_TOTAL, OLD_DB = load("partner_total.json"), load("db.json")


def err_of(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except MizanError as e:
        return e
    raise AssertionError("expected a MizanError")


def rules_of(violations):
    return {v["rule"] for v in violations}


class ExceptionTests(unittest.TestCase):
    def test_declared_error_surfaces_as_domain_error(self):
        e = err_of(run, RESERVE, {"product": 1, "wanted": 8}, SHOP, {"db.read"})
        self.assertEqual((e.stage, e.code, e.node), ("domain", "OutOfStock", "refuse"))

    def test_happy_path_never_evaluates_the_failing_branch(self):
        r = run(RESERVE, {"product": 1, "wanted": 5}, SHOP, {"db.read"})
        self.assertEqual(r.value, 2)

    def test_try_catches_and_returns_fallback(self):
        r = run(FALLBACK, {"product": 1, "wanted": 8, "fallback": 99}, SHOP, {"db.read"})
        self.assertEqual(r.value, 99)

    def test_undeclared_and_unused_raises(self):
        g = copy.deepcopy(RESERVE)
        g["raises"] = []
        self.assertEqual(err_of(check, g, SCHEMA, DOMAIN).code, "RAISES_UNDECLARED")
        g["raises"] = ["OutOfStock", "Other"]
        self.assertEqual(err_of(check, g, SCHEMA, DOMAIN).code, "RAISES_UNUSED")

    def test_unreachable_catch_is_a_compile_error(self):
        g = copy.deepcopy(FALLBACK)
        g["nodes"]["safe"]["catch"] = "Nope"
        self.assertEqual(err_of(check, g, SCHEMA, DOMAIN).code, "CATCH_UNREACHABLE")

    def test_error_names_are_pascal_case(self):
        g = copy.deepcopy(RESERVE)
        g["nodes"]["refuse"]["error"] = "out_of_stock"
        self.assertEqual(err_of(check, g, SCHEMA, DOMAIN).code, "BAD_ERROR_NAME")

    def test_hints_and_did_you_mean(self):
        g = copy.deepcopy(OLD_TOTAL)
        g["nodes"]["total"]["op"] = "sumn"
        e = err_of(structure, g)
        self.assertEqual(e.code, "UNKNOWN_OP")
        self.assertIn("sum", e.detail["did_you_mean"])
        g = copy.deepcopy(OLD_TOTAL)
        g["nodes"]["amts"]["field"] = "amout"
        e = err_of(check, g, OLD_DB["schema"])
        self.assertEqual(e.detail["did_you_mean"], ["amount"])
        g = copy.deepcopy(OLD_TOTAL)
        g["nodes"]["zero_m"] = {"op": "const", "type": "Int", "value": 0}
        self.assertIn("hint", err_of(check, g, OLD_DB["schema"]).to_dict())


class DomainTests(unittest.TestCase):
    def _graph(self, params, returns, nodes, out):
        return {"mizan": "0.1", "params": params, "returns": returns, "effects": [],
                "nodes": nodes, "out": out}

    def test_ids_of_different_things_cannot_be_mixed(self):
        g = {"mizan": "0.1", "params": {"p": "ProductId"}, "returns": "Int", "effects": ["db.read"],
             "nodes": {"p": {"op": "param", "name": "p"},
                       "inv": {"op": "db.scan", "table": "invoices"},
                       "mine": {"op": "filter_eq", "in": ["inv", "p"], "field": "partner"},
                       "n": {"op": "len", "in": ["mine"]}}, "out": "n"}
        e = err_of(check, g, SCHEMA, DOMAIN)
        self.assertEqual((e.code, e.node), ("TYPE_MISMATCH", "mine"))

    def test_raw_int_is_not_a_qty(self):
        g = self._graph({"q": "Qty"}, "Qty",
                        {"q": {"op": "param", "name": "q"},
                         "one": {"op": "const", "type": "Int", "value": 1},
                         "s": {"op": "add", "in": ["q", "one"]}}, "s")
        self.assertEqual(err_of(check, g, SCHEMA, DOMAIN).code, "TYPE_MISMATCH")

    def test_wrap_and_unwrap(self):
        g = self._graph({"raw": "Int"}, "ProductId",
                        {"raw": {"op": "param", "name": "raw"},
                         "w": {"op": "wrap", "in": ["raw"], "as": "ProductId"}}, "w")
        g["mizan"] = "0.2"
        self.assertEqual(run(g, {"raw": 3}, SHOP, set()).value, 3)
        g = self._graph({"x": "Int"}, "Int",
                        {"x": {"op": "param", "name": "x"},
                         "u": {"op": "unwrap", "in": ["x"]}}, "u")
        g["mizan"] = "0.2"
        self.assertEqual(err_of(check, g, SCHEMA, DOMAIN).code, "TYPE_MISMATCH")

    def test_bounded_context_is_enforced(self):
        g = copy.deepcopy(RESERVE)
        g["nodes"]["moves"]["table"] = "invoices"
        e = err_of(check, g, SCHEMA, DOMAIN)
        self.assertEqual(e.code, "CONTEXT_VIOLATION")
        self.assertEqual(e.detail["owned_by"], ["accounting"])

    def test_unknown_context_and_bad_domain(self):
        g = copy.deepcopy(RESERVE)
        g["context"] = "inventry"
        e = err_of(check, g, SCHEMA, DOMAIN)
        self.assertEqual((e.code, e.detail["did_you_mean"]), ("UNKNOWN_CONTEXT", ["inventory"]))
        self.assertEqual(err_of(check, RESERVE, SCHEMA, {"types": {"qty": "Int"}}).code, "BAD_DOMAIN")


class ScenarioTests(unittest.TestCase):
    def test_showcase_programs_are_green(self):
        for g in (RESERVE, FALLBACK):
            res = run_scenarios(g, SHOP)
            self.assertTrue(res and all(r["passed"] for r in res), [r for r in res if not r["passed"]])

    def test_red_scenario_explains_itself(self):
        g = copy.deepcopy(RESERVE)
        g["scenarios"][0]["then"] = {"result": 3}
        red = [r for r in run_scenarios(g, SHOP) if not r["passed"]]
        self.assertEqual(len(red), 1)
        self.assertIn("expected result 3 but got result 2", red[0]["message"])

    def test_bad_scenario_shape(self):
        g = copy.deepcopy(RESERVE)
        del g["scenarios"][0]["title"]
        self.assertEqual(err_of(structure, g).code, "BAD_SCENARIO")

    def test_gherkin(self):
        text = to_gherkin(RESERVE)
        for needle in ("Feature: reserve_stock", "Bounded context: inventory",
                       "Rule: may fail with OutOfStock", "Scenario: Zero units is a caller bug",
                       "Then it fails with OutOfStock", "Given table stock_moves holds 0 row(s)"):
            self.assertIn(needle, text)

    def test_mutation_kills_everything_for_the_showcase(self):
        m = mutation_test(RESERVE, SHOP)
        self.assertEqual((m["total"], m["killed"], m["survivors"]), (6, 6, []))
        self.assertEqual(mutation_test(FALLBACK, SHOP)["killed"], 7)

    def test_missing_scenario_leaves_a_survivor(self):
        g = copy.deepcopy(RESERVE)
        del g["scenarios"][1]            # "exactly what is on hand"
        m = mutation_test(g, SHOP)
        self.assertIn("enough: ge -> gt", m["survivors"])
        self.assertLess(m["score"], 1.0)

    def test_untested_contract_is_reported(self):
        g = {"mizan": "0.2", "label": "echo", "params": {"x": "Int"}, "returns": "Int", "effects": [],
             "nodes": {"x": {"op": "param", "name": "x"},
                       "zero": {"op": "const", "type": "Int", "value": 0},
                       "ok": {"op": "gt", "in": ["x", "zero"]}},
             "pre": ["ok"], "out": "x",
             "scenarios": [{"title": "echo", "when": {"x": 5}, "then": {"result": 5}}]}
        res = run_scenarios(g, {})
        m = mutation_test(g, {})
        self.assertEqual(m["killed"], 0)
        self.assertEqual(contract_coverage(g, res, m), ["pre[0]"])


class LintTests(unittest.TestCase):
    def test_showcase_is_clean(self):
        self.assertEqual(lint(RESERVE, SHOP, DEFAULT_POLICY), [])
        self.assertEqual(lint(FALLBACK, SHOP, DEFAULT_POLICY), [])

    def test_dead_node(self):
        g = copy.deepcopy(RESERVE)
        g["nodes"]["junk"] = {"op": "const", "type": "Qty", "value": 0}
        self.assertIn("no_dead_nodes", rules_of(lint(g, SHOP, DEFAULT_POLICY)))

    def test_duplicate_subgraph_reported_once(self):
        g = copy.deepcopy(RESERVE)
        g["nodes"].update({
            "moves2": {"op": "db.scan", "table": "stock_moves"},
            "mine2": {"op": "filter_eq", "in": ["moves2", "product"], "field": "product"},
            "qtys2": {"op": "pluck", "in": ["mine2"], "field": "qty"},
            "on_hand2": {"op": "sum", "in": ["qtys2"]}})
        g["nodes"]["left"]["in"] = ["on_hand2", "wanted"]
        dup = [v for v in lint(g, SHOP, DEFAULT_POLICY) if v["rule"] == "no_duplicate_subgraphs"]
        self.assertEqual(len(dup), 1)

    def test_magic_constants_need_a_why(self):
        self.assertNotIn("magic_consts_need_why", rules_of(lint(STRICT, SHOP, DEFAULT_POLICY)))
        g = copy.deepcopy(STRICT)
        del g["nodes"]["cap"]["why"]
        self.assertIn("magic_consts_need_why", rules_of(lint(g, SHOP, DEFAULT_POLICY)))

    def test_unused_param_cqs_context_label_names(self):
        g = copy.deepcopy(RESERVE)
        g["params"]["extra"] = "Qty"
        g["effects"] = ["db.read", "io.print"]
        del g["context"]
        g["label"] = "ReserveStock"
        found = rules_of(lint(g, SHOP, DEFAULT_POLICY))
        self.assertTrue({"no_unused_params", "forbidden_effect_mixes", "require_context",
                         "snake_case_names"} <= found)

    def test_missing_glossary_entry(self):
        db = copy.deepcopy(SHOP)
        del db["domain"]["glossary"]["Qty"]
        v = [x for x in lint(RESERVE, db, DEFAULT_POLICY) if x["rule"] == "require_glossary"]
        self.assertEqual(len(v), 1)
        self.assertIn("Qty", v[0]["message"])

    def test_policy_is_tunable(self):
        tight = {**DEFAULT_POLICY, "max_params": 1}
        self.assertIn("max_params", rules_of(lint(RESERVE, SHOP, tight)))


class GateAndLiskovTests(unittest.TestCase):
    def test_gate_passes_the_showcase(self):
        r = gate(RESERVE, SHOP, DEFAULT_POLICY)
        self.assertTrue(r["ok"])
        self.assertEqual(r["mutation"]["killed"], 6)
        self.assertIn("RESULT: PASS", format_gate(r))

    def test_gate_rejects_a_program_without_scenarios(self):
        r = gate(OLD_TOTAL, OLD_DB, DEFAULT_POLICY)
        self.assertFalse(r["ok"])
        self.assertFalse(r["tests"]["ok"])

    def test_gate_stops_at_compile_errors_with_a_hint(self):
        g = copy.deepcopy(RESERVE)
        g["nodes"]["none"] = {"op": "const", "type": "Int", "value": 0}
        r = gate(g, SHOP, DEFAULT_POLICY)
        self.assertFalse(r["compile"]["ok"])
        self.assertIn("hint:", format_gate(r))

    def test_liskov(self):
        ok, why = substitutable(RESERVE, LENIENT)
        self.assertTrue(ok, why)
        ok, why = substitutable(RESERVE, STRICT)
        self.assertEqual((ok, [w["rule"] for w in why]), (False, ["pre"]))
        g = copy.deepcopy(RESERVE)
        del g["post"]
        self.assertEqual([w["rule"] for w in substitutable(RESERVE, g)[1]], ["post"])
        g = copy.deepcopy(RESERVE)
        g["nodes"]["refuse"]["error"] = "Gone"
        g["raises"] = ["Gone"]
        self.assertIn("raises", [w["rule"] for w in substitutable(RESERVE, g)[1]])


class IdentityAndVersionTests(unittest.TestCase):
    def test_why_scenarios_and_label_do_not_change_identity(self):
        g = copy.deepcopy(STRICT)
        g["nodes"]["cap"]["why"] = "a completely different reason"
        g["scenarios"] = [{"title": "x", "when": {"product": 1, "wanted": 1}, "then": {"result": 9}}]
        g["label"] = "renamed"
        self.assertEqual(fn_hash(STRICT, TYPES), fn_hash(g, TYPES))

    def test_raises_is_part_of_identity(self):
        g = copy.deepcopy(RESERVE)
        g["raises"] = []
        self.assertNotEqual(fn_hash(RESERVE, TYPES), fn_hash(g, TYPES))

    def test_v01_programs_cannot_use_v02_features(self):
        g = copy.deepcopy(OLD_TOTAL)
        g["raises"] = []
        self.assertEqual(err_of(structure, g).code, "NEEDS_V02")
        g = copy.deepcopy(OLD_TOTAL)
        g["nodes"]["total"]["why"] = "because"
        self.assertEqual(err_of(structure, g).code, "NEEDS_V02")
        g = copy.deepcopy(OLD_TOTAL)
        g["nodes"]["x"] = {"op": "fail", "error": "Boom", "type": "Int", "message": "m"}
        self.assertEqual(err_of(structure, g).code, "NEEDS_V02")


class CliTests(unittest.TestCase):
    def _run(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(list(argv))
        return code, buf.getvalue()

    def test_exit_codes_and_output(self):
        db = str(EX / "shop_db.json")
        code, out = self._run("gate", str(EX / "reserve_stock.json"), "--db", db)
        self.assertEqual((code, "RESULT: PASS" in out), (0, True))
        code, out = self._run("gate", str(EX / "partner_total.json"), "--db", str(EX / "db.json"))
        self.assertEqual((code, "RESULT: FAIL" in out), (1, True))
        code, out = self._run("run", str(EX / "reserve_stock.json"), "--db", db,
                              "--arg", "product=1", "--arg", "wanted=5", "--grant", "db.read")
        self.assertEqual((code, json.loads(out)["result"]), (0, 2))
        code, out = self._run("subst", str(EX / "reserve_stock.json"), str(EX / "reserve_stock_strict.json"))
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
