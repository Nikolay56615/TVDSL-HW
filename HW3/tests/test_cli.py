"""Проверяем настоящий запуск CLI, файлы, эталоны типов и коды завершения."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "HW3" / "examples"
CASES = ROOT / "HW3" / "tests" / "cases.json"
SIMPLE = "main() returns r:int uses local { local = 1; r = local; }"
UNKNOWN = "main() returns r:int {\n    r = missing + 1;\n}\n"


class CommandLineTests(unittest.TestCase):
    def command(self, *arguments, cwd=ROOT):
        environment = os.environ.copy()
        # Импорт модуля из другого каталога проверяет пути таблицы и эталонов.
        environment["PYTHONPATH"] = str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
        return subprocess.run(
            [sys.executable, "-m", "HW3.funnytypes", *map(str, arguments)],
            cwd=cwd, env=environment, capture_output=True, text=True, encoding="utf-8",
            timeout=20, check=False)

    def fixture_command(self, cases, *arguments):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "cases.json"
            fixture.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")
            return self.command("test", "--cases", fixture, *arguments)

    def test_positive_file_has_types_and_keeps_declared_annotations(self):
        completed = self.command("check", EXAMPLES / "good_basic.funny")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "Ошибок нет.\n")
        self.assertEqual(completed.stderr, "")
        completed = self.command("check", EXAMPLES / "good_basic.funny", "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertTrue(output["ok"])
        self.assertEqual(output["diagnostics"], [])
        function = output["ast"]["declarations"][0]
        self.assertEqual(function["name"], "main")
        self.assertEqual(function["locals"][0]["type"], "int")
        self.assertIsNone(function["locals"][1]["type"])
        self.assertEqual(function["locals"][1]["inferred_type"], "int")
        self.assertEqual(function["body"]["statements"][0]["value"]["inferred_type"], "int")
        self.assertEqual(completed.stderr, "")
        completed = self.command("check", EXAMPLES / "good_basic.funny", "--format", "tree")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.startswith("Module @1:1\n"))
        self.assertIn('inferred_type: "int"', completed.stdout)

    def test_all_examples_have_the_expected_validity(self):
        examples = sorted(EXAMPLES.glob("*.funny"))
        self.assertEqual(len(examples), 8)
        for example in examples:
            with self.subTest(example=example.name):
                expected = example.name.startswith("good_")
                completed = self.command("check", example)
                self.assertEqual(completed.returncode, 0 if expected else 1, completed.stderr)
                if expected:
                    self.assertEqual(completed.stdout, "Ошибок нет.\n")
                else:
                    self.assertTrue(completed.stdout.strip())
                    for line in completed.stdout.splitlines():
                        self.assertRegex(line, r"^\d+:\d+: semantic \[[a-z_]+\]: ")

    def test_semantic_error_has_code_and_token_position(self):
        completed = self.command("check", "--text", UNKNOWN, "--format", "json")
        self.assertEqual(completed.returncode, 1, completed.stderr)
        diagnostic = json.loads(completed.stdout)["diagnostics"][0]
        self.assertEqual(diagnostic["phase"], "semantic")
        self.assertEqual(diagnostic["code"], "unknown_variable")
        self.assertEqual((diagnostic["line"], diagnostic["col"]), (2, 9))
        self.assertIn("missing", diagnostic["message"])
        self.assertEqual(completed.stderr, "")

    def test_independent_errors_are_all_reported(self):
        completed = self.command("check", EXAMPLES / "bad_types.funny", "--format", "json")
        self.assertEqual(completed.returncode, 1, completed.stderr)
        diagnostics = json.loads(completed.stdout)["diagnostics"]
        self.assertEqual([diagnostic["code"] for diagnostic in diagnostics],
                         ["readonly_assignment", "readonly_assignment", "type_mismatch", "type_mismatch"])
        self.assertEqual([diagnostic["line"] for diagnostic in diagnostics], [2, 3, 4, 5])

    def test_lexical_and_syntax_errors_survive_checking_in_utf8(self):
        completed = self.command("check", "--text", "f() returns r:int { r=😀; }", "--format", "json")
        self.assertEqual(completed.returncode, 1, completed.stderr)
        diagnostics = json.loads(completed.stdout)["diagnostics"]
        lexical = next(diagnostic for diagnostic in diagnostics if diagnostic["phase"] == "lexical")
        self.assertEqual((lexical["line"], lexical["col"]), (1, 23))
        self.assertIn("😀", lexical["message"])
        self.assertTrue(any(diagnostic["phase"] == "syntax" for diagnostic in diagnostics))
        self.assertNotIn("UnicodeEncodeError", completed.stderr)

    def test_error_tree_requires_explicit_tree_format(self):
        for output_format in (None, "json", "tree"):
            with self.subTest(output_format=output_format):
                arguments = [] if output_format is None else ["--format", output_format]
                completed = self.command("check", "--text", UNKNOWN, *arguments)
                self.assertEqual(completed.returncode, 1, completed.stderr)
                self.assertEqual(completed.stderr, "")
                if output_format == "json":
                    output = json.loads(completed.stdout)
                    self.assertEqual(set(output), {"ok", "diagnostics"})
                    self.assertFalse(output["ok"])
                    self.assertEqual(output["diagnostics"][0]["code"], "unknown_variable")
                elif output_format == "tree":
                    self.assertTrue(completed.stdout.startswith("Module @1:1\n"), completed.stdout)
                    self.assertIn("Function @1:1", completed.stdout)
                    self.assertIn("Assign @2:5", completed.stdout)
                    self.assertIn('inferred_type: "error"', completed.stdout)
                    self.assertIn("2:9: semantic [unknown_variable]:", completed.stdout)
                else:
                    self.assertEqual(completed.stdout,
                                     "2:9: semantic [unknown_variable]: Неизвестная переменная 'missing'\n")

    def test_empty_text_is_a_program_error(self):
        completed = self.command("check", "--text", "")
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIn("1:1: syntax:", completed.stdout)
        self.assertNotIn("Module", completed.stdout)

    def test_unicode_arrow_formula_and_array_tuple_types(self):
        contracts = self.command("check", EXAMPLES / "good_contracts.funny", "--format", "json")
        self.assertEqual(contracts.returncode, 0, contracts.stderr)
        quantified = json.loads(contracts.stdout)["ast"]["declarations"][0]["predicate"]
        self.assertEqual(quantified["inferred_type"], "bool")
        self.assertEqual(quantified["predicate"]["op"], "->")
        tuple_call = self.command("check", EXAMPLES / "good_tuple.funny", "--format", "json")
        self.assertEqual(tuple_call.returncode, 0, tuple_call.stderr)
        function = json.loads(tuple_call.stdout)["ast"]["declarations"][1]
        self.assertEqual(function["body"]["statements"][0]["value"]["inferred_type"], ["int", "int[]"])
        self.assertEqual([local["inferred_type"] for local in function["locals"]], ["int", "int[]"])

    def test_out_preserves_error_status_and_utf8_for_all_formats(self):
        source = "f() returns r:int { r=😀; }"
        with tempfile.TemporaryDirectory() as directory:
            for output_format in (None, "json", "tree"):
                with self.subTest(output_format=output_format):
                    destination = Path(directory) / ("результат." + (output_format or "default"))
                    arguments = [] if output_format is None else ["--format", output_format]
                    completed = self.command("check", "--text", source, *arguments, "--out", destination)
                    self.assertEqual(completed.returncode, 1, completed.stderr)
                    self.assertEqual(completed.stdout, "")
                    output = destination.read_bytes()
                    self.assertFalse(output.startswith(b"\xef\xbb\xbf"))
                    self.assertNotIn(b"\r\n", output)
                    self.assertIn("😀".encode("utf-8"), output)
                    text = output.decode("utf-8")
                    if output_format == "json":
                        document = json.loads(text)
                        self.assertFalse(document["ok"])
                        self.assertNotIn("ast", document)
                    elif output_format == "tree":
                        self.assertTrue(text.startswith("Module @1:1\n"))
                    else:
                        self.assertIn(": lexical:", text)
                        self.assertIn(": syntax:", text)
                        for line in text.splitlines():
                            self.assertRegex(line, r"^\d+:\d+: (lexical|syntax|semantic)(?: \[[^]]+\])?: ")

    def test_utf8_bom_and_crlf_keep_semantic_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bom.funny"
            source.write_bytes(b"\xef\xbb\xbf" + UNKNOWN.replace("\n", "\r\n").encode("utf-8"))
            completed = self.command("check", source, "--format", "json")
            self.assertEqual(completed.returncode, 1, completed.stderr)
            diagnostic = json.loads(completed.stdout)["diagnostics"][0]
            self.assertEqual((diagnostic["line"], diagnostic["col"]), (2, 9))

    def test_explicit_lexer_table_is_used(self):
        completed = self.command("check", "--text", SIMPLE, "--table", ROOT / "HW1/generated/dfa.min.json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "Ошибок нет.\n")

    def test_default_cases_and_table_are_independent_of_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = self.command("check", "--text", SIMPLE, cwd=directory)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout, "Ошибок нет.\n")
            completed = self.command("test", cwd=directory)
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            count = len(json.loads(CASES.read_text(encoding="utf-8"))["cases"])
            self.assertIn("%d cases: %d passed, 0 failed" % (count, count), completed.stdout)

    def test_default_verbose_cases_are_numbered_and_readable(self):
        completed = self.command("test", "-v")
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
        self.assertEqual(len([line for line in completed.stdout.splitlines() if line.startswith("[")]), len(cases))
        self.assertIn("[01/%02d] PASS" % len(cases), completed.stdout)
        for fragment in ("Программа:", "Ожидалось:", "Получено:", "semantic [unknown_variable]",
                         "Диагностика: совпадает с эталоном", "Типы: совпадают с эталоном"):
            self.assertIn(fragment, completed.stdout)
        self.assertNotIn("\x1b", completed.stdout)

    def test_custom_cases_match_codes_positions_and_message_substrings(self):
        case = {"name": "Неизвестное имя", "input": UNKNOWN, "valid": False,
                "diagnostics": [{"phase": "semantic", "code": "unknown_variable",
                                 "line": 2, "col": 9, "message": "missing"}]}
        completed = self.fixture_command([case], "-v")
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn("[01/01] PASS  Неизвестное имя", completed.stdout)
        self.assertIn("Ожидаемая диагностика:", completed.stdout)
        self.assertIn('"code": "unknown_variable"', completed.stdout)
        self.assertIn("semantic [unknown_variable] 2:9:", completed.stdout)

    def test_custom_cases_check_type_paths_and_tuple_type_lists(self):
        case = {"name": "Типы кортежа", "input": (EXAMPLES / "good_tuple.funny").read_text(encoding="utf-8"),
                "valid": True, "diagnostics": [], "type_checks": [
                    {"path": "declarations[1].locals[0].inferred_type", "type": "int"},
                    {"path": "ast.declarations[1].locals[1].inferred_type", "type": "int[]"},
                    {"path": "declarations[1].body.statements[0].value.inferred_type", "type": ["int", "int[]"]}]}
        completed = self.fixture_command([case], "-v")
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn("Типы: совпадают с эталоном", completed.stdout)

    def test_fixture_validity_mismatch_returns_one_and_explains_result(self):
        completed = self.fixture_command([{"name": "wrong_validity", "input": UNKNOWN, "valid": True}], "-v")
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIn("[01/01] FAIL  wrong_validity", completed.stdout)
        self.assertIn("Ожидалось: корректная программа", completed.stdout)
        self.assertIn("Получено: некорректная программа", completed.stdout)
        self.assertIn("valid: ожидалось true, получено false", completed.stdout)
        self.assertIn("1 cases: 0 passed, 1 failed", completed.stdout)

    def test_fixture_diagnostic_mismatch_reports_first_field(self):
        case = {"name": "wrong_code", "input": UNKNOWN, "valid": False,
                "diagnostics": [{"code": "unknown_callable", "line": 1}]}
        completed = self.fixture_command([case], "-v")
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIn('diagnostics[0].code: ожидалось "unknown_callable", получено "unknown_variable"',
                      completed.stdout)
        self.assertNotIn("diagnostics[0].line: ожидалось", completed.stdout)

    def test_fixture_diagnostic_count_is_exact(self):
        case = {"name": "missing_diagnostic", "input": UNKNOWN, "valid": False, "diagnostics": []}
        completed = self.fixture_command([case])
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIn("diagnostics.length: ожидалось 0, получено 1", completed.stdout)

    def test_fixture_type_mismatch_reports_first_path(self):
        case = {"name": "wrong_type", "input": SIMPLE, "valid": True, "type_checks": [
            {"path": "declarations[0].locals[0].inferred_type", "type": "int[]"},
            {"path": "declarations[0].returns[0].inferred_type", "type": "bool"}]}
        completed = self.fixture_command([case], "-v")
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIn('ast.declarations[0].locals[0].inferred_type: ожидалось "int[]", получено "int"',
                      completed.stdout)
        self.assertNotIn("ast.declarations[0].returns[0]", completed.stdout)

    def test_fixture_missing_type_path_is_a_failed_expectation(self):
        case = {"name": "missing_field", "input": SIMPLE, "valid": True,
                "type_checks": [{"path": "declarations[9].locals[0].inferred_type", "type": "int"}]}
        completed = self.fixture_command([case])
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIn("ast.declarations[9].locals[0].inferred_type:", completed.stdout)
        self.assertIn("<нет такого поля>", completed.stdout)
        self.assertNotIn("Traceback", completed.stderr)

    def test_full_ast_snapshot_reports_first_different_field(self):
        actual = json.loads(self.command("check", "--text", SIMPLE, "--format", "json").stdout)["ast"]
        actual["declarations"][0]["name"] = "wrong_name"
        case = {"name": "wrong_ast", "input": SIMPLE, "valid": True, "ast": actual}
        completed = self.fixture_command([case], "-v")
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIn('ast.declarations[0].name: ожидалось "wrong_name", получено "main"', completed.stdout)

    def test_argument_errors_return_two(self):
        for arguments in ((), ("check",), ("check", "ignored", "--text", SIMPLE),
                          ("check", "--text", SIMPLE, "--format", "yaml"),
                          ("check", "--text", SIMPLE, "--format", "diagnostics"), ("unknown",)):
            with self.subTest(arguments=arguments):
                completed = self.command(*arguments)
                self.assertEqual(completed.returncode, 2)
                self.assertIn("error:", completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)

    def test_file_output_and_table_errors_return_two(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            malformed = Path(directory) / "bad_table.json"
            malformed.write_text("{}", encoding="utf-8")
            for arguments in (("check", missing), ("test", "--cases", missing),
                              ("check", "--text", SIMPLE, "--table", missing),
                              ("check", "--text", SIMPLE, "--table", malformed),
                              ("check", "--text", SIMPLE, "--out", missing / "out.json")):
                with self.subTest(arguments=arguments):
                    completed = self.command(*arguments)
                    self.assertEqual(completed.returncode, 2)
                    self.assertIn("error:", completed.stderr)
                    self.assertNotIn("Traceback", completed.stderr)

    def test_malformed_fixture_and_unsafe_paths_return_two(self):
        valid = {"name": "fixture", "input": SIMPLE, "valid": True}
        documents = [
            "{", "[]", '{"cases": {}}',
            json.dumps({"cases": [{**valid, "valid": "yes"}]}),
            json.dumps({"cases": [{**valid, "diagnostics": [{"line": 0}]}]}),
            json.dumps({"cases": [{**valid, "type_checks": [{"path": "x.__class__()", "type": "int"}]}]}),
            json.dumps({"cases": [{**valid, "type_checks": [{"path": "declarations[-1]", "type": "int"}]}]}),
            json.dumps({"cases": [{**valid, "type_checks": [{"path": "declarations[0]", "type": "string"}]}]})]
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "cases.json"
            for document in documents:
                with self.subTest(document=document):
                    fixture.write_text(document, encoding="utf-8")
                    completed = self.command("test", "--cases", fixture)
                    self.assertEqual(completed.returncode, 2)
                    self.assertIn("error:", completed.stderr)
                    self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
