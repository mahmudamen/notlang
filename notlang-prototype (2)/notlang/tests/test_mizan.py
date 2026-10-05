import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mizan import MizanError, check, fn_hash, run, structure, view  # noqa: E402
from mizan.ops import OPS  # noqa: E402

EX = ROOT / "examples"


def load(name):
    return json.loads((EX / name).read_text(encoding="utf-8"))


DB = load("db.json")
TOTAL = load("partner_total.json")
JOURNAL = load("journal_balance.json")


def code_of(fn, *a, **kw):
    with_err = None
    try:
        fn(*a, **kw)
    except MizanError as e:
        with_err = e
    assert with_err is not None, "expected a MizanError"
    return with_err.code


def rename_nodes(graph, prefix):
    g = copy.deepcopy(graph)
    m = {k: prefix + k for k in g["nodes"]}
    g["nodes"] = {m[k]: {**n, **({"in": [m[r] for r in n["in"]]} if "in" in n else {})}
                  for k, n in g["nodes"].items()}
    g["out"] = m[g["out"]]
    g["pre"] = [m[x] for x in g.get("pre", [])]
    g["post"] = [m[x] for x in g.get("post", [])]
    return g


class RunTests(unittest.TestCase):
    def test_partner_total(self):
        r = run(TOTAL, {"pid": 1}, DB, {"db.read"})
        self.assertEqual(str(r.value), "150.00")
        self.assertEqual(r.effects, ["db.read"])

    def test_empty_sum_is_zero(self):
        r = run(TOTAL, {"pid": 99}, DB, {"db.read"})
        self.assertEqual(str(r.value), "0")

    def test_pre_failure(self):
        self.assertEqual(code_of(run, TOTAL, {"pid": 0}, DB, {"db.read"}), "PRE_FAILED")

    def test_journal_balanced_and_unbalanced(self):
        ok = run(JOURNAL, {"eid": 1}, DB, {"db.read"})
        self.assertEqual(str(ok.value), "100.00")
        self.assertEqual(code_of(run, JOURNAL, {"eid": 2}, DB, {"db.read"}), "POST_FAILED")

    def test_effect_denied_without_grant(self):
        self.assertEqual(code_of(run, TOTAL, {"pid": 1}, DB, set()), "EFFECT_DENIED")

    def test_bad_args(self):
        self.assertEqual(code_of(run, TOTAL, {}, DB, {"db.read"}), "BAD_ARGS")
        self.assertEqual(code_of(run, TOTAL, {"pid": "1"}, DB, {"db.read"}), "BAD_LITERAL")
        self.assertEqual(code_of(run, TOTAL, {"pid": True}, DB, {"db.read"}), "BAD_LITERAL")

    def test_float_money_banned(self):
        g = copy.deepcopy(TOTAL)
        g["nodes"]["zero_m"]["value"] = 0.1
        self.assertEqual(code_of(check, g, DB["schema"]), "BAD_LITERAL")

    def test_print_effect_and_lazy_if(self):
        g = {"mizan": "0.1", "params": {}, "returns": "Int", "effects": ["io.print"],
             "nodes": {
                 "t": {"op": "const", "type": "Bool", "value": True},
                 "a": {"op": "const", "type": "Int", "value": 1},
                 "b": {"op": "const", "type": "Int", "value": 2},
                 "pa": {"op": "io.print", "in": ["a"]},
                 "pb": {"op": "io.print", "in": ["b"]},
                 "pick": {"op": "if", "in": ["t", "pa", "pb"]}},
             "out": "pick"}
        r = run(g, {}, {}, {"io.print"})
        self.assertEqual(r.value, 1)
        self.assertEqual(r.printed, ["1"])  # the untaken branch never ran


class CheckTests(unittest.TestCase):
    def test_type_mismatch(self):
        g = copy.deepcopy(TOTAL)
        g["nodes"]["zero_m"] = {"op": "const", "type": "Int", "value": 0}
        with self.assertRaises(MizanError) as cm:
            check(g, DB["schema"])
        self.assertEqual(cm.exception.code, "TYPE_MISMATCH")
        self.assertEqual(cm.exception.node, "res_ok")

    def test_undeclared_and_unused_effects(self):
        g = copy.deepcopy(TOTAL)
        g["effects"] = []
        self.assertEqual(code_of(check, g, DB["schema"]), "EFFECT_UNDECLARED")
        g["effects"] = ["db.read", "io.print"]
        self.assertEqual(code_of(check, g, DB["schema"]), "EFFECT_UNUSED")

    def test_cycle(self):
        g = copy.deepcopy(TOTAL)
        g["nodes"]["a"] = {"op": "add", "in": ["b", "b"]}
        g["nodes"]["b"] = {"op": "add", "in": ["a", "a"]}
        self.assertEqual(code_of(structure, g), "CYCLE")

    def test_unknown_op_ref_and_key(self):
        g = copy.deepcopy(TOTAL)
        g["nodes"]["x"] = {"op": "teleport"}
        self.assertEqual(code_of(structure, g), "UNKNOWN_OP")
        g = copy.deepcopy(TOTAL)
        g["nodes"]["mine"]["in"] = ["inv", "ghost"]
        self.assertEqual(code_of(structure, g), "UNKNOWN_REF")
        g = copy.deepcopy(TOTAL)
        g["comment"] = "humans love comments"
        self.assertEqual(code_of(structure, g), "UNKNOWN_KEY")

    def test_unknown_table_and_field(self):
        g = copy.deepcopy(TOTAL)
        g["nodes"]["inv"]["table"] = "ghosts"
        self.assertEqual(code_of(check, g, DB["schema"]), "UNKNOWN_TABLE")
        g = copy.deepcopy(TOTAL)
        g["nodes"]["amts"]["field"] = "nope"
        self.assertEqual(code_of(check, g, DB["schema"]), "UNKNOWN_FIELD")

    def test_result_not_allowed_in_pre_or_body(self):
        g = copy.deepcopy(TOTAL)
        g["pre"] = ["res_ok"]
        self.assertEqual(code_of(check, g, DB["schema"]), "RESULT_IN_PRE")

    def test_return_mismatch(self):
        g = {"mizan": "0.1", "params": {}, "returns": "Int", "effects": [],
             "nodes": {"m": {"op": "const", "type": "Money", "value": "1"}}, "out": "m"}
        self.assertEqual(code_of(check, g), "RETURN_MISMATCH")


class HashTests(unittest.TestCase):
    def test_renaming_nodes_keeps_hash(self):
        self.assertEqual(fn_hash(TOTAL), fn_hash(rename_nodes(TOTAL, "x_")))

    def test_label_and_money_spelling_do_not_matter(self):
        g = copy.deepcopy(TOTAL)
        g["label"] = "something_else"
        g["nodes"]["zero_m"]["value"] = "0.00"
        self.assertEqual(fn_hash(TOTAL), fn_hash(g))

    def test_meaning_change_changes_hash(self):
        g = copy.deepcopy(TOTAL)
        g["nodes"]["amts"]["field"] = "id"
        self.assertNotEqual(fn_hash(TOTAL), fn_hash(g))
        self.assertNotEqual(fn_hash(TOTAL), fn_hash(JOURNAL))


class ViewAndSpecTests(unittest.TestCase):
    def test_view(self):
        text = view(TOTAL)
        self.assertIn("body: sum(filter(db.invoices, partner == pid).amount)", text)
        self.assertIn("pre:  pid > 0", text)
        self.assertIn("fx:   [db.read]", text)

    def test_specs_document_every_op(self):
        specs = {"0.1": (ROOT / "SPEC-001.md").read_text(encoding="utf-8"),
                 "0.2": (ROOT / "SPEC-002-quality.md").read_text(encoding="utf-8")}
        for op, spec in OPS.items():
            self.assertIn(f"`{op}`", specs[spec["since"]],
                          f"the spec for v{spec['since']} does not mention op {op}")


if __name__ == "__main__":
    unittest.main()
