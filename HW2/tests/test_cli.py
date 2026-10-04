"""Контракт CLI: коды завершения, выходные файлы и эталонные примеры из репозитория."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "HW2" / "examples"


class CommandLineTests(unittest.TestCase):
    def command(self, *arguments):
        return subprocess.run([sys.executable, "-m", "HW2.funnyparse", *map(str, arguments)],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                              timeout=15, check=False)

    def test_positive_file_outputs_json(self):
        completed = self.command("parse", EXAMPLES / "good_basic.funny")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertTrue(output["ok"])
        self.assertEqual(output["diagnostics"], [])
        self.assertEqual(output["ast"]["declarations"][0]["name"], "main")
        self.assertEqual(completed.stderr, "")

    def test_negative_file_outputs_diagnostics_and_returns_one(self):
        completed = self.command("parse", EXAMPLES / "bad_recovery.funny")
        self.assertEqual(completed.returncode, 1, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertFalse(output["ok"])
        self.assertTrue(output["diagnostics"])
        self.assertEqual(output["diagnostics"][0]["phase"], "syntax")
        self.assertEqual([function["name"] for function in output["ast"]["declarations"]],
                         ["broken", "correct"])

    def test_unicode_arrow_file_outputs_successful_utf8_json(self):
        completed = self.command("parse", EXAMPLES / "good_formulas.funny")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertTrue(output["ok"])
        self.assertEqual(output["diagnostics"], [])
        predicate = output["ast"]["declarations"][0]["predicate"]["predicate"]
        self.assertEqual(predicate["op"], "->")
        self.assertEqual(predicate["pos"], {"line": 3, "col": 45})

    def test_emoji_error_outputs_readable_utf8_diagnostic(self):
        completed = self.command("parse", "--text", "f() returns r:int { r=😀; }")
        self.assertEqual(completed.returncode, 1, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertFalse(output["ok"])
        lexical = next(diagnostic for diagnostic in output["diagnostics"]
                       if diagnostic["phase"] == "lexical")
        self.assertEqual((lexical["line"], lexical["col"]), (1, 23))
        self.assertIn("😀", lexical["message"])
        self.assertNotIn("UnicodeEncodeError", completed.stderr)

    def test_tree_format_includes_nodes_and_coordinates(self):
        completed = self.command("parse", EXAMPLES / "good_basic.funny", "--format", "tree")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.startswith("Module @1:1\n"), completed.stdout)
        self.assertIn("Function @1:1", completed.stdout)
        self.assertIn("Assign @2:5", completed.stdout)
        self.assertIn('op: "*"', completed.stdout)

    def test_out_writes_utf8_json_and_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            for output_format in ("json", "tree"):
                with self.subTest(output_format=output_format):
                    destination = Path(directory) / ("result." + output_format)
                    completed = self.command("parse", EXAMPLES / "good_basic.funny",
                                             "--format", output_format, "--out", destination)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertEqual(completed.stdout, "")
                    text = destination.read_text(encoding="utf-8")
                    if output_format == "json":
                        self.assertTrue(json.loads(text)["ok"])
                    else:
                        self.assertTrue(text.startswith("Module @1:1\n"))

    def test_out_keeps_error_ast_and_status(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "invalid.json"
            completed = self.command("parse", "--text", "f() returns r:int { r=; }", "--out", destination)
            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertEqual(completed.stdout, "")
            output = json.loads(destination.read_text(encoding="utf-8"))
            self.assertFalse(output["ok"])
            self.assertTrue(output["diagnostics"])

    def test_missing_input_or_table_returns_two_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.funny"
            for arguments in (("parse", missing),
                              ("parse", EXAMPLES / "good_basic.funny", "--table", missing)):
                with self.subTest(arguments=arguments):
                    completed = self.command(*arguments)
                    self.assertEqual(completed.returncode, 2)
                    self.assertIn("error:", completed.stderr)
                    self.assertNotIn("Traceback", completed.stderr)

    def test_incorrect_cli_arguments_return_two(self):
        for arguments in (("parse",), ("parse", EXAMPLES / "good_basic.funny", "--text", "")):
            with self.subTest(arguments=arguments):
                completed = self.command(*arguments)
                self.assertEqual(completed.returncode, 2)
                self.assertIn("error:", completed.stderr)

    def test_checked_in_fixture_command(self):
        completed = self.command("test")
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn("25 cases: 25 passed, 0 failed", completed.stdout)

    def test_fixture_mismatch_returns_one(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "cases.json"
            fixture.write_text(json.dumps({"cases": [{"name": "wrong_expectation", "input": "", "valid": True}]}),
                               encoding="utf-8")
            completed = self.command("test", "--cases", fixture)
            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertIn("FAIL  wrong_expectation", completed.stdout)
            self.assertIn("1 cases: 0 passed, 1 failed", completed.stdout)

    def test_utf8_bom_and_crlf_file_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "with_bom.funny"
            source.write_bytes(b"\xef\xbb\xbfmain() returns r:int {\r\n  r = 1;\r\n}\r\n")
            completed = self.command("parse", source)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            statement = json.loads(completed.stdout)["ast"]["declarations"][0]["body"]["statements"][0]
            self.assertEqual(statement["pos"], {"line": 2, "col": 3})


if __name__ == "__main__":
    unittest.main()
