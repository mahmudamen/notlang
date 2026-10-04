import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.mock import MockModel  # noqa: E402
from bench.run_bench import load, run_bench, summarize  # noqa: E402
from mizan import check  # noqa: E402

DB = load(ROOT / "bench" / "db.json")
TASKS = load(ROOT / "bench" / "tasks.json")


class BenchTests(unittest.TestCase):
    def test_worked_example_is_valid(self):
        check(load(ROOT / "examples" / "has_invoices.json"), DB["schema"])

    def test_reference_solutions_are_all_correct_first_try(self):
        s = summarize(run_bench(MockModel(slips=False), TASKS, DB))
        self.assertEqual(s, {"tasks": 10, "first_try_accepted": 10, "accepted_in_budget": 10,
                             "correct": 10, "incorrect_but_accepted": 0})

    def test_scripted_slips_are_repaired_or_exposed(self):
        s = summarize(run_bench(MockModel(slips=True), TASKS, DB))
        # 4 tasks are valid first time; 4 slips are repaired from structured errors;
        # 2 semantic slips are accepted but wrong, and only the task cases expose them.
        self.assertEqual(s, {"tasks": 10, "first_try_accepted": 4, "accepted_in_budget": 10,
                             "correct": 8, "incorrect_but_accepted": 2})


if __name__ == "__main__":
    unittest.main()
