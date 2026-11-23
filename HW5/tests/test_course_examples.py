"""Проверки графа из TVDSL/practices/P09_temporal_specs.md."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from HW5.checker import ROOT, verify


COURSE = Path(__file__).resolve().parent / "course"


class CourseGraphTests(unittest.TestCase):
    def verify_graph(self, filename):
        local_spin = ROOT / ".tools" / "spin.exe"
        spin = os.environ.get("SPIN", str(local_spin) if local_spin.is_file() else "spin")
        with TemporaryDirectory(prefix="p09-tests-") as output:
            report, directory = verify(
                "correct", 2, ("safety", "response", "return_idle"), output,
                spin=spin, cc=os.environ.get("CC", "gcc"), model=COURSE / filename,
            )
            results = {result["property"]: result for result in report["results"]}
            self.assertTrue(results["safety"]["holds"])
            self.assertTrue(results["return_idle"]["holds"])
            if not results["response"]["holds"]:
                trace = Path(results["response"]["trace"]).read_text(encoding="utf-8")
                self.assertIn("START OF CYCLE", trace)
                cycle = trace.split("START OF CYCLE", 1)[1]
                self.assertIn("STATE state=s1", cycle)
                self.assertNotIn("STATE state=s2", cycle)
            return results

    def test_p09_self_loop_can_delay_response_forever(self):
        results = self.verify_graph("p09_waiting.pml")
        self.assertFalse(results["response"]["holds"])
        self.assertEqual(results["response"]["counterexample"], "cycle")

    def test_p09_exercise_six_removes_the_counterexample(self):
        results = self.verify_graph("p09_without_waiting.pml")
        self.assertTrue(results["response"]["holds"])
        self.assertIsNone(results["response"]["trace"])
