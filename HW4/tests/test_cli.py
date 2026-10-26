"""Проверки публичных команд, кодов завершения и читаемых эталонов."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from HW4.funnyir.cli import compare_outcomes, run_case, typed_equal


ROOT = Path(__file__).resolve().parents[2]
SOURCE = "main(x:int) returns r:int {r=x+1;}"
CONSTANT = "main() returns r:int {r=2+3;}"
CSE_SOURCE = "main(a:int,b:int) returns r:int uses x:int,y:int {x=a+b;y=a+b;r=x+y;}"


class CLITests(unittest.TestCase):
    def run_cli(self, *arguments, cwd=ROOT):
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONPATH"] = str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
        process = subprocess.run([sys.executable, "-m", "HW4.funnyir", *arguments],
                                 cwd=cwd, env=environment, capture_output=True)
        process.stdout = process.stdout.decode("utf-8")
        process.stderr = process.stderr.decode("utf-8")
        self.assertNotIn("Traceback", process.stderr)
        return process

    def assert_launch_error(self, *arguments):
        process = self.run_cli(*arguments)
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertTrue(process.stderr)
        return process

    def test_build_json_contains_both_ir_and_analysis(self):
        process = self.run_cli("build", "--text", CONSTANT, "--format", "json")
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["before"]["version"], 1)
        self.assertEqual(result["after"]["version"], 1)
        self.assertIn("main", result["analysis_before"])
        self.assertIn("main", result["analysis_after"])
        self.assertIn("metrics", result)

    def test_build_text_is_readable(self):
        process = self.run_cli("build", "--text", CONSTANT)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.splitlines(), ["Ошибок нет."])
        self.assertEqual(process.stderr, "")
        process = self.run_cli("build", "--text", CONSTANT, "--format", "text")
        self.assertEqual(process.returncode, 0, process.stderr)
        for title in ("IR ДО оптимизаций", "IR ПОСЛЕ оптимизаций", "Метрики"):
            self.assertIn(title, process.stdout)

    def test_no_opt_preserves_ir(self):
        for source in (CONSTANT, CSE_SOURCE):
            with self.subTest(source=source):
                process = self.run_cli("build", "--text", source, "--no-opt", "--format", "json")
                self.assertEqual(process.returncode, 0, process.stderr)
                result = json.loads(process.stdout)
                self.assertEqual(result["before"], result["after"])

    def test_pass_flags_are_accepted(self):
        process = self.run_cli("run", "--text", CONSTANT, "--no-constants", "--no-simplify",
                               "--no-cse", "--no-dce")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), [5])

    def test_no_cse_restores_repeated_source_computation(self):
        for flags, expected_count in (((), 2), (("--no-cse",), 3)):
            with self.subTest(flags=flags):
                process = self.run_cli("build", "--text", CSE_SOURCE, "--no-constants",
                                       "--no-simplify", "--no-dce", "--format", "json", *flags)
                self.assertEqual(process.returncode, 0, process.stderr)
                result = json.loads(process.stdout)
                for version, count in (("before", 3), ("after", expected_count)):
                    instructions = [instruction for function in result[version]["functions"]
                                    for block in function["blocks"] for instruction in block["instructions"]]
                    self.assertEqual(sum(instruction["op"] == "binary" and instruction["operator"] == "+"
                                         for instruction in instructions), count)
                if flags:
                    self.assertEqual(result["before"], result["after"])

    def test_run_with_and_without_cse_has_same_results_and_errors(self):
        cases = [(CSE_SOURCE, "[2,3]", {"result": [10]}),
                 ("main(a:int,b:int) returns r:int uses x:int,y:int {"
                  "x=a+b;y=a+b;r=(x+y)/0;}", "[2,3]", {"code": "division_by_zero"}),
                 ("main(a:int) returns r:int uses x:int,y:int,z:int {"
                  "y=x+a;z=x+a;r=y+z;}", "[2]", {"code": "uninitialized"})]
        for source, arguments, expected in cases:
            observations = []
            for flags in ((), ("--no-cse",)):
                with self.subTest(source=source, flags=flags):
                    process = self.run_cli("run", "--text", source, "--args", arguments, "--compare", *flags)
                    self.assertEqual(process.returncode, 0, process.stderr)
                    actual = json.loads(process.stdout)
                    self.assertIs(actual["equivalent"], True)
                    self.assertEqual(actual["before"], actual["after"])
                    if "result" in expected:
                        self.assertEqual(actual["after"], expected)
                    else:
                        self.assertEqual(actual["after"]["error"]["code"], expected["code"])
                    observations.append(actual)
            self.assertEqual(*observations)

    def test_run_outputs_json_array(self):
        process = self.run_cli("run", "--text", SOURCE, "--args", "[8]")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), [9])

    def test_run_before(self):
        process = self.run_cli("run", "--text", CONSTANT, "--before")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), [5])

    def test_compare_results(self):
        process = self.run_cli("run", "--text", SOURCE, "--args", "[8]", "--compare")
        result = json.loads(process.stdout)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIs(result["equivalent"], True)
        self.assertEqual(result["before"], {"result": [9]})
        self.assertEqual(result["after"], {"result": [9]})

    def test_compare_equal_traps(self):
        process = self.run_cli("run", "--text", "main() returns r:int {r=1/0;}", "--compare")
        result = json.loads(process.stdout)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIs(result["equivalent"], True)
        self.assertEqual(result["before"]["error"]["code"], "division_by_zero")
        self.assertIn("pos", result["after"]["error"])

    def test_single_trap_exits_one(self):
        process = self.run_cli("run", "--text", "main() returns r:int {r=1/0;}")
        self.assertEqual(process.returncode, 1)
        self.assertEqual(json.loads(process.stdout)["error"]["code"], "division_by_zero")

    def test_limit_is_inconclusive(self):
        source = "main() returns r:int {r=0;while(true)r=r+1;}"
        process = self.run_cli("run", "--text", source, "--compare", "--max-steps", "20")
        result = json.loads(process.stdout)
        self.assertEqual(process.returncode, 1)
        self.assertIsNone(result["equivalent"])
        self.assertEqual(result["comparison"], "inconclusive")

    def test_multiple_results_and_arrays(self):
        source = "main(a:int[]) returns r:int[],n:int {r=a;n=length(a);}"
        process = self.run_cli("run", "--text", source, "--args", "[[1,2]]")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), [[1, 2], 2])

    def test_selected_function(self):
        process = self.run_cli("run", "--text", "other() returns r:int {r=4;}", "--function", "other")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), [4])

    def test_error_diagnostics_in_build_json(self):
        process = self.run_cli("build", "--text", "main() returns r:int {r=missing;}", "--format", "json")
        result = json.loads(process.stdout)
        self.assertEqual(process.returncode, 1)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["before"])
        self.assertEqual(result["diagnostics"][0]["code"], "unknown_variable")

    def test_error_diagnostics_in_build_text(self):
        for output_format in (None, "text"):
            with self.subTest(output_format=output_format):
                arguments = [] if output_format is None else ["--format", output_format]
                process = self.run_cli("build", "--text", "main() returns r:int {r=missing;}", *arguments)
                self.assertEqual(process.returncode, 1)
                self.assertEqual(process.stderr, "")
                self.assertEqual(len(process.stdout.splitlines()), 1)
                self.assertIn("semantic", process.stdout)
                self.assertIn("unknown_variable", process.stdout)
                self.assertNotIn("IR ДО", process.stdout)
                self.assertNotIn("Метрики", process.stdout)

    def test_run_invalid_source(self):
        process = self.run_cli("run", "--text", "main() returns r:int {r=missing;}")
        self.assertEqual(process.returncode, 1)
        self.assertIn("diagnostics", json.loads(process.stdout))

    def test_utf8_file_and_output(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            source = Path(directory) / "программа.funny"
            output = Path(directory) / "результат.txt"
            source.write_text("\ufeff// комментарий\n" + CONSTANT, encoding="utf-8")
            for output_format in (None, "text", "json"):
                with self.subTest(output_format=output_format):
                    arguments = [] if output_format is None else ["--format", output_format]
                    process = self.run_cli("build", str(source), *arguments, "--out", str(output))
                    self.assertEqual(process.returncode, 0, process.stderr)
                    self.assertEqual(process.stdout, "")
                    self.assertEqual(process.stderr, "")
                    contents = output.read_bytes()
                    self.assertFalse(contents.startswith(b"\xef\xbb\xbf"))
                    self.assertNotIn(b"\r\n", contents)
                    text = contents.decode("utf-8")
                    if output_format is None:
                        self.assertEqual(text, "Ошибок нет.\n")
                    elif output_format == "text":
                        self.assertIn("Метрики", text)
                    else:
                        self.assertTrue(json.loads(text)["ok"])

    def test_run_output_file(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            output = Path(directory) / "run.json"
            process = self.run_cli("run", "--text", CONSTANT, "--out", str(output))
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), [5])

    def test_graph_outputs(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            cfg = Path(directory) / "cfg.dot"
            graph = Path(directory) / "interference.dot"
            process = self.run_cli("build", "--text", SOURCE, "--cfg-dot", str(cfg),
                                   "--interference-dot", str(graph), "--function", "main")
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout.splitlines(), ["Ошибок нет."])
            self.assertIn("digraph", cfg.read_text(encoding="utf-8"))
            self.assertIn("graph", graph.read_text(encoding="utf-8"))

    def test_default_fixture_suite(self):
        process = self.run_cli("test")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("0 failed", process.stdout)

    def test_saved_example_outputs(self):
        examples = ROOT / "HW4" / "examples"
        for name, arguments in (("good_basic", [7]), ("good_cse", [2, 3])):
            with self.subTest(example=name):
                source = str(examples / (name + ".funny"))
                process = self.run_cli("build", source, "--format", "json")
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(json.loads(process.stdout),
                                 json.loads((examples / (name + ".output.json")).read_text(encoding="utf-8")))
                process = self.run_cli("build", source, "--format", "text")
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(process.stdout.replace("\r\n", "\n"),
                                 (examples / (name + ".output.txt")).read_text(encoding="utf-8"))
                process = self.run_cli("run", source, "--args", json.dumps(arguments), "--compare")
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(json.loads(process.stdout),
                                 json.loads((examples / (name + ".run.json")).read_text(encoding="utf-8")))

    def test_example_expectations(self):
        examples = ROOT / "HW4" / "examples"
        cases = json.loads((examples / "expected_results.json").read_text(encoding="utf-8"))["examples"]
        for case in cases:
            with self.subTest(file=case["file"]):
                case = {**case, "name": case["file"],
                        "input": (examples / case["file"]).read_text(encoding="utf-8")}
                actual, errors = run_case(case)
                self.assertEqual(errors, [], actual)

    def test_verbose_custom_suite(self):
        case = {"name": "Проверка числа", "input": CONSTANT, "result": [5]}
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            cases = Path(directory) / "cases.json"
            cases.write_text(json.dumps({"cases": [case]}, ensure_ascii=False), encoding="utf-8")
            process = self.run_cli("test", "--cases", str(cases), "-v")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        for text in ("[01/01] PASS", "Программа:", "аргументы: []", "Ожидалось: результат [5]",
                     "Получено ДО:", "Получено ПОСЛЕ:", "наблюдения совпали"):
            self.assertIn(text, process.stdout)

    def test_wrong_expected_result_fails(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            cases = Path(directory) / "cases.json"
            cases.write_text(json.dumps({"cases": [{"name": "Ошибка эталона", "input": CONSTANT,
                                                     "result": [99]}]}), encoding="utf-8")
            process = self.run_cli("test", "--cases", str(cases))
        self.assertEqual(process.returncode, 1)
        self.assertIn("1 failed", process.stdout)

    def test_fixture_requires_unambiguous_expectation(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            cases = Path(directory) / "cases.json"
            cases.write_text(json.dumps({"cases": [{"name": "bad", "input": CONSTANT,
                                                     "result": [5], "error": "division_by_zero"}]}),
                             encoding="utf-8")
            self.assert_launch_error("test", "--cases", str(cases))

    def test_fixture_diagnostics_need_valid_coordinates(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            cases = Path(directory) / "cases.json"
            cases.write_text(json.dumps({"cases": [{"name": "bad", "input": "", "valid": False,
                                                     "diagnostics": [{"line": 0}]}]}), encoding="utf-8")
            self.assert_launch_error("test", "--cases", str(cases))

    def test_missing_input(self):
        self.assert_launch_error("build")

    def test_ambiguous_input(self):
        self.assert_launch_error("build", "file.funny", "--text", CONSTANT)

    def test_missing_file(self):
        self.assert_launch_error("build", "does-not-exist.funny")

    def test_invalid_args_json(self):
        self.assert_launch_error("run", "--text", SOURCE, "--args", "[")

    def test_args_must_be_list(self):
        self.assert_launch_error("run", "--text", SOURCE, "--args", "8")

    def test_wrong_argument_count(self):
        self.assert_launch_error("run", "--text", SOURCE)

    def test_boolean_is_not_integer_argument(self):
        self.assert_launch_error("run", "--text", SOURCE, "--args", "[true]")

    def test_float_is_not_integer_argument(self):
        self.assert_launch_error("run", "--text", SOURCE, "--args", "[1.5]")

    def test_array_elements_must_be_integers(self):
        self.assert_launch_error("run", "--text", "main(a:int[]) returns r:int {r=0;}",
                                 "--args", "[[1,true]]")

    def test_unknown_function(self):
        self.assert_launch_error("run", "--text", CONSTANT, "--function", "missing")

    def test_before_and_compare_are_exclusive(self):
        self.assert_launch_error("run", "--text", CONSTANT, "--before", "--compare")

    def test_positive_step_limit(self):
        self.assert_launch_error("run", "--text", CONSTANT, "--max-steps", "0")

    def test_unknown_graph_function(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            self.assert_launch_error("build", "--text", CONSTANT, "--function", "missing",
                                     "--cfg-dot", str(Path(directory) / "cfg.dot"))

    def test_missing_table(self):
        self.assert_launch_error("build", "--text", CONSTANT, "--table", "missing-table.json")

    def test_typed_comparison_distinguishes_bool(self):
        self.assertFalse(typed_equal([True], [1]))
        self.assertFalse(typed_equal([[False]], [[0]]))
        self.assertEqual(compare_outcomes({"result": [True]}, {"result": [1]}), (False, "different"))

    def test_comparison_distinguishes_results_and_traps(self):
        self.assertEqual(compare_outcomes({"result": [1]}, {"error": {"code": "uninitialized"}}),
                         (False, "different"))
        self.assertEqual(compare_outcomes({"error": {"code": "array_bounds"}},
                                          {"error": {"code": "division_by_zero"}}),
                         (False, "different"))

    def test_comparison_does_not_claim_limits_equivalent(self):
        for code in ("step_limit", "recursion_limit"):
            self.assertEqual(compare_outcomes({"error": {"code": code}}, {"error": {"code": code}}),
                             (None, "inconclusive"))


if __name__ == "__main__":
    unittest.main()
