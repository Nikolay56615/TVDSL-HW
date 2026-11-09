from importlib.util import find_spec
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from HW4.funnyir import compile_source
from PROJECT.funnyjvm.translation import build_query, solve_query


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "PROJECT" / "examples" / "translation"
HAS_Z3 = find_spec("z3") is not None


def example(name):
    return json.loads((EXAMPLES / (name + ".json")).read_text(encoding="utf-8"))


def block(*instructions):
    return {"instructions": list(instructions)}


class TranslationInputTests(unittest.TestCase):
    def test_only_integer_straight_line_blocks_are_accepted(self):
        for instruction, diagnostic in (
            ({"op": "branch", "args": [{"var": "v:x"}]}, "Неподдерживаемая инструкция"),
            ({"op": "return", "args": [{"var": "missing"}]}, "прочитан до определения"),
            ({"op": "return", "args": [{"const": True}]}, "целое const"),
            ({"op": "return", "args": []}, "возвращать значения"),
        ):
            with self.subTest(instruction=instruction):
                pair = example("add_zero")
                pair["after"] = block(instruction)
                with self.assertRaisesRegex(ValueError, diagnostic):
                    build_query(pair)

    def test_rejects_different_result_counts(self):
        pair = example("add_zero")
        pair["after"] = block({"op": "return", "args": [{"var": "v:x"}, {"const": 0}]})
        with self.assertRaisesRegex(ValueError, "одинаковое число"):
            build_query(pair)


@unittest.skipUnless(HAS_Z3, "Для проверки SMT нужен z3-solver")
class TranslationSolverTests(unittest.TestCase):
    def solve(self, pair):
        return solve_query(build_query(pair), pair["inputs"])

    def test_two_correct_rules_have_no_counterexample(self):
        for name in ("add_zero", "multiply_one"):
            with self.subTest(example=name):
                self.assertEqual(self.solve(example(name)), {"status": "unsat"})

    def test_checks_actual_hw4_blocks_before_and_after_optimization(self):
        result = compile_source("main(x:int) returns r:int {r=(x+0)*1;}")
        self.assertTrue(result.ok, result.diagnostics)
        before = result.before["functions"][0]["blocks"][0]
        after = result.after["functions"][0]["blocks"][0]
        self.assertLess(len(after["instructions"]), len(before["instructions"]))
        self.assertEqual(self.solve({"inputs": ["v:x"], "before": before, "after": after}),
                         {"status": "unsat"})

    def test_division_by_zero_is_an_observable_difference(self):
        pair = example("bad_divide_zero")
        self.assertEqual(self.solve(pair), {"status": "sat", "inputs": {"v:x": 0}})
        pair["after"] = block(
            {"op": "binary", "operator": "/", "dest": "t:1", "args": [{"const": 0}, {"var": "v:x"}]},
            {"op": "return", "args": [{"const": 0}]},
        )
        self.assertEqual(self.solve(pair), {"status": "unsat"})

    def test_overflow_signed_division_reassignment_and_multiple_results(self):
        before = block(
            {"op": "binary", "operator": "+", "dest": "x", "args": [{"const": 2147483647}, {"const": 1}]},
            {"op": "binary", "operator": "/", "dest": "y", "args": [{"const": -7}, {"const": 3}]},
            {"op": "copy", "dest": "x", "args": [{"var": "x"}]},
            {"op": "return", "args": [{"var": "x"}, {"var": "y"}]},
        )
        outputs = [{"const": -2147483648}, {"const": -2}]
        pair = {"inputs": [], "before": before, "after": block({"op": "return", "args": outputs})}
        self.assertEqual(self.solve(pair), {"status": "unsat"})
        outputs[1] = {"const": -3}
        self.assertEqual(self.solve(pair), {"status": "sat", "inputs": {}})

    def test_cli_returns_counterexample_and_exports_the_query(self):
        with TemporaryDirectory(prefix="funny-smt-tests-") as temporary:
            output = Path(temporary) / "query.smt2"
            process = subprocess.run(
                [sys.executable, "-B", "-m", "PROJECT.funnyjvm", "validate",
                 str(EXAMPLES / "bad_divide_zero.json"), "--smt-out", str(output)],
                cwd=ROOT, capture_output=True, encoding="utf-8",
            )
            self.assertEqual(process.returncode, 1, process.stderr)
            self.assertEqual(json.loads(process.stdout), {"status": "sat", "inputs": {"v:x": 0}})
            self.assertEqual(output.read_text(encoding="utf-8"),
                             build_query(example("bad_divide_zero")) + "(check-sat)\n")
