import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from HW4.funnyir import compile_source
from PROJECT.funnyjvm import emit_class
from PROJECT.funnyjvm.cli import build_runtime, encode_arguments, launch


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "PROJECT" / "examples" / "runtime_asserts.funny"


class RuntimeAssertsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = TemporaryDirectory(prefix="funny-assert-tests-")
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        build_runtime(cls.directory)

    def compile(self, source):
        result = compile_source(source)
        self.assertTrue(result.ok, result.diagnostics)
        return result

    def invoke(self, module, arguments, *, enabled=True):
        bytecode = emit_class(module, "TestAsserts", runtime_asserts=enabled)
        (self.directory / "TestAsserts.class").write_bytes(bytecode)
        main = next(function for function in module["functions"] if function["name"] == "main")
        return launch(self.directory, "TestAsserts", "main", encode_arguments(arguments, main["params"]))

    def assert_result(self, process, values):
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), values)

    def assert_failure(self, process, code, message):
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assertEqual(process.stdout, "")
        self.assertIn(f"runtime [{code}]", process.stderr)
        self.assertIn(message, process.stderr)

    def test_example_reports_each_failure_at_its_source_position(self):
        result = self.compile(EXAMPLE.read_text(encoding="utf-8"))
        for phase, module in (("before", result.before), ("after", result.after)):
            with self.subTest(phase=phase):
                self.assert_result(self.invoke(module, [[3], 4]), [5])
                self.assert_failure(self.invoke(module, [[], 4]), "assertion_failed", "assert at 4:5")
                self.assert_failure(self.invoke(module, [[-3], 4]), "assertion_failed", "assert at 4:5")
                self.assert_failure(self.invoke(module, [[3], -1]), "assumption_failed", "assume at 5:5")

    def test_flag_off_skips_the_checks_and_their_expressions(self):
        result = self.compile("main(x:int) returns r:int {assert 1/x > 0; assume false; r=17;}")
        self.assert_result(self.invoke(result.after, [0], enabled=False), [17])
        self.assert_failure(self.invoke(result.after, [0]), "division_by_zero", "ArithmeticException")

    def test_optimized_code_retains_assignment_read_only_by_assert(self):
        result = self.compile("main(x:int) returns r:int uses tmp:int {tmp=x+1; assert tmp>0; r=7;}")
        self.assert_result(self.invoke(result.after, [0]), [7])
        self.assert_failure(self.invoke(result.after, [-2]), "assertion_failed", "assert at")

    def test_nested_formula_calls_and_short_circuit(self):
        result = self.compile(
            "guard(x:int) => x != 0 -> positive(10/x, -1);\n"
            "positive(x:int, y:int) => not (x <= y);\n"
            "main(x:int) returns r:int {assert guard(x) or x == -2; r=3;}"
        )
        for value in (0, 2, -2):
            with self.subTest(value=value):
                self.assert_result(self.invoke(result.after, [value]), [3])
        self.assert_failure(self.invoke(result.after, [-1]), "assertion_failed", "assert at 3:")

    def test_quantifier_diagnostic_is_limited_to_enabled_runtime_checks(self):
        source = "all() => forall(i:int | i == i);\nmain() returns r:int {assert all(); r=1;}"
        result = self.compile(source)
        self.assert_result(self.invoke(result.after, [], enabled=False), [1])
        with self.assertRaisesRegex(ValueError, r"1:10: --runtime-asserts .*Quantifier"):
            emit_class(result.after, runtime_asserts=True)

        result = self.compile("all() => forall(i:int | i == i);\nmain() requires all() returns r:int {r=1;}")
        self.assert_result(self.invoke(result.after, []), [1])

    def test_run_and_built_class_use_the_same_flag(self):
        def cli(*arguments):
            return subprocess.run(
                [sys.executable, "-B", "-m", "PROJECT.funnyjvm", *arguments],
                cwd=ROOT, capture_output=True, encoding="utf-8",
            )

        inputs = ("--args", "[[3],-1]")
        self.assert_result(cli("run", str(EXAMPLE), *inputs), [0])
        run = cli("run", str(EXAMPLE), "--runtime-asserts", *inputs)
        self.assert_failure(run, "assumption_failed", "assume at 5:5")
        with TemporaryDirectory(prefix="funny-build-tests-") as temporary:
            build = cli("build", str(EXAMPLE), "--runtime-asserts", "--out", temporary)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = launch(Path(temporary), "FunnyModule", "main", "3\n-1\n")
            self.assert_failure(run, "assumption_failed", "assume at 5:5")
