"""Запуск сгенерированных классов и проверка публичного ABI."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from HW4.funnyir import compile_source
from PROJECT.funnyjvm import emit_class
from PROJECT.funnyjvm.cli import _jdk_tool, build_runtime, encode_arguments, launch


ROOT = Path(__file__).resolve().parents[2]
HW4_EXAMPLES = Path(sys.modules["HW4.funnyir"].__file__).resolve().parents[1] / "examples"
PROJECT_EXAMPLE = ROOT / "PROJECT" / "examples" / "arrays_and_tuple.funny"


class JVMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = TemporaryDirectory(prefix="funny-jvm-tests-")
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        build_runtime(cls.directory)

    def compile(self, source):
        result = compile_source(source)
        self.assertTrue(result.ok, result.diagnostics)
        return result

    def invoke(self, module, function, arguments):
        (self.directory / "TestModule.class").write_bytes(emit_class(module, "TestModule"))
        signature = next(item for item in module["functions"] if item["name"] == function)
        inputs = encode_arguments(arguments, signature["params"])
        return launch(self.directory, "TestModule", function, inputs)

    def test_hw4_examples_before_and_after_optimization(self):
        expected = json.loads((HW4_EXAMPLES / "expected_results.json").read_text(encoding="utf-8"))
        for case in expected["examples"]:
            source = (HW4_EXAMPLES / case["file"]).read_text(encoding="utf-8")
            result = compile_source(source)
            if not case.get("valid", True):
                with self.subTest(file=case["file"]):
                    self.assertFalse(result.ok)
                    self.assertGreaterEqual(len(result.diagnostics), len(case["diagnostics"]))
                    for expected_item, actual in zip(case["diagnostics"], result.diagnostics):
                        self.assertEqual(expected_item, {k: actual.to_dict()[k] for k in expected_item})
                continue
            for phase, module in (("before", result.before), ("after", result.after)):
                with self.subTest(file=case["file"], phase=phase):
                    process = self.invoke(module, case["function"], case["args"])
                    if "error" in case:
                        self.assertEqual(process.returncode, 1, process.stderr)
                        self.assertIn("[" + case["error"] + "]", process.stderr)
                    else:
                        self.assertEqual(process.returncode, 0, process.stderr)
                        self.assertEqual(json.loads(process.stdout), case["result"])

    def test_mixed_tuple_round_trip_and_scalar_tuple_abi(self):
        result = self.compile(PROJECT_EXAMPLE.read_text(encoding="utf-8"))
        for module in (result.before, result.after):
            process = self.invoke(module, "main", [[4, 2, 7]])
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout), [[2, 7, 7], 5])
            process = self.invoke(module, "minmax", [[4, 2, 7]])
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout), [2, 7])
        listing = subprocess.run(
            [_jdk_tool("javap"), "-s", "-classpath", str(self.directory), "TestModule"],
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertIn("public final class TestModule", listing)
        self.assertIn("public static int[] minmax(ImmutableIntArray)", listing)
        self.assertIn("descriptor: (LImmutableIntArray;)[I", listing)
        self.assertIn("descriptor: (LImmutableIntArray;)[Ljava/lang/Object;", listing)

    def test_array_assignment_and_update_preserve_input(self):
        result = self.compile(
            "main(a:int[]) returns b:int[], original:int {b=a; b[0]=42; original=a[0];}"
        )
        process = self.invoke(result.after, "main", [[8, 9]])
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), [[42, 9], 8])
        factory = self.compile("main(a:int[]) returns b:int[] {b=a;}")
        process = self.invoke(factory.after, "main", [[]])
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), [[]])

    def test_undefined_local_does_not_turn_into_zero(self):
        result = self.compile("main(p:int) returns r:int uses x:int {if(p>0)x=4; r=x;}")
        for module in (result.before, result.after):
            valid = self.invoke(module, "main", [1])
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual(json.loads(valid.stdout), [4])
            invalid = self.invoke(module, "main", [0])
            self.assertEqual(invalid.returncode, 1, invalid.stderr)
            self.assertIn("[uninitialized]", invalid.stderr)

    def test_large_method_has_wide_local_slots_and_branches(self):
        # Ветка длиннее 32 КиБ, а номера локальных слотов выходят за 255.
        source = "main(x:int) returns r:int {if(x>0){" + "r=x;" * 2400 + "}else r=9;}"
        module = self.compile(source).before
        for value, expected in ((1, 1), (0, 9)):
            process = self.invoke(module, "main", [value])
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout), [expected])

    def test_cli_build_run_and_diagnostics(self):
        with TemporaryDirectory(prefix="funny-jvm-cli-") as temporary:
            directory = Path(temporary)
            source = directory / "sample.funny"
            source.write_text("main(x:int) returns r:int {r=x+1;}", encoding="utf-8")
            out = directory / "classes"
            build = self.cli("build", str(source), "--class", "Sample", "--out", str(out))
            self.assertEqual(build.returncode, 0, build.stderr)
            self.assertEqual((out / "Sample.class").read_bytes()[:4], bytes.fromhex("CA FE BA BE"))
            process = launch(out, "Sample", "main", "41\n")
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout), [42])
            run = self.cli("run", str(source), "--args", "[41]", "--no-opt")
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout), [42])
            bad_args = self.cli("run", str(source), "--args", "[true]")
            self.assertEqual(bad_args.returncode, 2, bad_args.stderr)
            source.write_text("main(x:int) returns r:int {x=3; r=x;}", encoding="utf-8")
            bad_source = self.cli("build", str(source), "--class", "Rejected", "--out", str(out))
            self.assertEqual(bad_source.returncode, 1, bad_source.stderr)
            self.assertIn("readonly_assignment", bad_source.stderr)
            self.assertFalse((out / "Rejected.class").exists())

    @staticmethod
    def cli(*args):
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run(
            [sys.executable, "-B", "-m", "PROJECT.funnyjvm", *args],
            cwd=ROOT, env=env, capture_output=True, encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
