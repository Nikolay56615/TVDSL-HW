"""Программы TVDSL из всех четырнадцати шагов проекта."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from HW4.funnyir.cli import diagnostics_match, outcome
from PROJECT.funnyjvm import compile_source, emit_class
from PROJECT.funnyjvm.cli import build_runtime, encode_arguments, launch


COURSE = Path(__file__).resolve().parent / "course"
CASES = json.loads((COURSE / "cases.json").read_text(encoding="utf-8"))


class CourseInventoryTests(unittest.TestCase):
    def test_every_course_file_has_expectations_and_an_unchanged_original(self):
        metadata = json.loads((COURSE / "source.json").read_text(encoding="utf-8"))
        names = [case["file"] for case in CASES]
        self.assertEqual(len(names), len(set(names)), "Повторяющиеся случаи")
        originals = {path.relative_to(COURSE / "original").as_posix()
                     for path in (COURSE / "original").rglob("*.funny")}
        self.assertEqual(originals, set(names))
        self.assertEqual(originals, set(metadata["sha256"]))
        for name, expected in metadata["sha256"].items():
            with self.subTest(file=name):
                actual = hashlib.sha256((COURSE / "original" / name).read_bytes()).hexdigest()
                self.assertEqual(actual, expected)


class CourseExamplesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = TemporaryDirectory(prefix="funny-course-tests-")
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        build_runtime(cls.directory)

    def check_case(self, case):
        original = COURSE / "original" / case["file"]
        compiled = compile_source(original.read_text(encoding="utf-8-sig"))
        if "diagnostic" in case:
            self.assertFalse(compiled.ok, "Ошибочный исходник принят")
            self.assertTrue(any(diagnostics_match([case["diagnostic"]], [item.to_dict()])
                                for item in compiled.diagnostics), compiled.diagnostics)
            return
        self.assertTrue(compiled.ok, compiled.diagnostics)

        for phase, module in (("before", compiled.before), ("after", compiled.after)):
            for case_run in case["runs"]:
                with self.subTest(file=case["file"], phase=phase, function=case_run["function"],
                                  args=case_run["args"], runtime_asserts=case_run.get("runtime_asserts", False)):
                    self.check_execution(module, case_run)
            if "runtime_unsupported" in case:
                with self.subTest(phase=phase, runtime_asserts=True):
                    with self.assertRaisesRegex(ValueError, case["runtime_unsupported"]):
                        emit_class(module, runtime_asserts=True)

    def check_execution(self, module, case):
        checked_at_runtime = case.get("runtime_asserts", False)
        if not checked_at_runtime:
            observed = outcome(module, case["function"], case["args"], 100000, 128)
            if "error" in case:
                self.assertEqual(observed["error"]["code"], case["error"])
            else:
                self.assertEqual(observed, {"result": case["result"]})

        bytecode = emit_class(module, "CourseModule", runtime_asserts=checked_at_runtime)
        (self.directory / "CourseModule.class").write_bytes(bytecode)
        function = next(item for item in module["functions"] if item["name"] == case["function"])
        arguments = encode_arguments(case["args"], function["params"])
        process = launch(self.directory, "CourseModule", case["function"], arguments)
        if "error" in case:
            self.assertEqual(process.returncode, 1, process.stderr)
            self.assertEqual(process.stdout, "")
            self.assertIn("runtime [" + case["error"] + "]", process.stderr)
        else:
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout), case["result"])


def course_test(case):
    def test(self):
        self.check_case(case)
    test.__doc__ = case["file"] + (" — запись в параметр запрещена ТЗ" if "spec_conflict" in case else "")
    return test


for course_case in CASES:
    test_name = "test_" + course_case["file"].removesuffix(".funny").replace("/", "__")
    setattr(CourseExamplesTests, test_name, course_test(course_case))
