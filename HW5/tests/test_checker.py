import unittest

from HW5.checker import parse_verification


class VerificationOutputTests(unittest.TestCase):
    def test_completed_search_proves_property(self):
        output = "Full statespace search for:\nState-vector 32 byte, depth reached 40, errors: 0"
        self.assertEqual(parse_verification(output), {"holds": True, "counterexample": None})

    def test_assertion_is_a_finite_counterexample(self):
        output = ("pan:1: assertion violated !(ack&&expired)\nWarning: Search not completed\n"
                  "Full statespace search for:\nerrors: 1")
        self.assertEqual(parse_verification(output), {"holds": False, "counterexample": "state"})

    def test_acceptance_cycle_is_a_liveness_counterexample(self):
        output = ("pan:1: acceptance cycle\nWarning: Search not completed\n"
                  "Full statespace search for:\nerrors: 1")
        self.assertEqual(parse_verification(output), {"holds": False, "counterexample": "cycle"})

    def test_depth_limit_is_not_a_counterexample_or_a_proof(self):
        for errors in (0, 1):
            output = ("error: max search depth too small\nFull statespace search for:\n"
                      f"errors: {errors}")
            with self.subTest(errors=errors), self.assertRaises(ValueError):
                parse_verification(output)

    def test_incomplete_or_unrecognized_output_is_rejected(self):
        for output in (
            "", "errors: 0", "Full statespace search for:",
            "Full statespace search for:\nSearch not completed\nerrors: 0",
            "Full statespace search for:\nout of memory\nerrors: 0",
            "Full statespace search for:\ninvalid end state\nerrors: 1",
        ):
            with self.subTest(output=output), self.assertRaises(ValueError):
                parse_verification(output)
