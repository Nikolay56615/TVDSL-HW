"""Ручные эталоны CFG/живости: развилка, цикл и одновременные значения."""

from copy import deepcopy
import unittest

from HW4.funnyir.analysis import analyze, build_cfg


def var(name):
    return {"var": name}


def const(value):
    return {"const": value}


def instruction(op, **fields):
    return {"op": op, "pos": {"line": 1, "col": 1}, **fields}


def block(label, *instructions):
    return {"label": label, "instructions": list(instructions)}


def function(blocks, params=()):
    return {
        "name": "main",
        "entry": "B0",
        "params": [{"name": name, "type": "int"} for name in params],
        "blocks": blocks,
    }


class AnalysisTests(unittest.TestCase):
    def assert_valid_coloring(self, result):
        graph, colors = result["interference"], result["colors"]
        self.assertEqual(set(graph), set(colors))
        for register, neighbors in graph.items():
            self.assertNotIn(register, neighbors)
            self.assertEqual(neighbors, sorted(neighbors))
            for neighbor in neighbors:
                self.assertIn(register, graph[neighbor])
                self.assertNotEqual(colors[register], colors[neighbor])

    def test_diamond_cfg_and_exact_liveness(self):
        fn = function(
            [
                block("B0", instruction("branch", args=[var("v:c")], **{"then": "B1", "else": "B2"})),
                block("B1", instruction("binary", dest="v:x", operator="+", args=[var("v:a"), const(1)]), instruction("jump", target="B3")),
                block("B2", instruction("binary", dest="v:x", operator="-", args=[var("v:b"), const(1)]), instruction("jump", target="B3")),
                block("B3", instruction("binary", dest="t:r", operator="*", args=[var("v:x"), const(2)]), instruction("return", args=[var("t:r")])),
                block("BU", instruction("return", args=[])),
            ],
            params=("a", "b", "c"),
        )
        original = deepcopy(fn)
        result = analyze(fn)
        self.assertEqual(result["cfg"], {
            "B0": {"successors": ["B1", "B2"], "predecessors": [], "reachable": True},
            "B1": {"successors": ["B3"], "predecessors": ["B0"], "reachable": True},
            "B2": {"successors": ["B3"], "predecessors": ["B0"], "reachable": True},
            "B3": {"successors": [], "predecessors": ["B1", "B2"], "reachable": True},
            "BU": {"successors": [], "predecessors": [], "reachable": False},
        })
        self.assertEqual(result["blocks"], {
            "B0": {"use": ["v:c"], "defs": [], "live_in": ["v:a", "v:b", "v:c"], "live_out": ["v:a", "v:b"]},
            "B1": {"use": ["v:a"], "defs": ["v:x"], "live_in": ["v:a"], "live_out": ["v:x"]},
            "B2": {"use": ["v:b"], "defs": ["v:x"], "live_in": ["v:b"], "live_out": ["v:x"]},
            "B3": {"use": ["v:x"], "defs": ["t:r"], "live_in": ["v:x"], "live_out": []},
            "BU": {"use": [], "defs": [], "live_in": [], "live_out": []},
        })
        self.assertEqual(fn, original)
        self.assertEqual(analyze(fn), result)
        self.assertEqual(result["colors"], {"t:r": 0, "v:a": 0, "v:b": 1, "v:c": 2, "v:x": 0})
        self.assert_valid_coloring(result)

    def test_loop_requires_fixed_point(self):
        fn = function([
            block("B0", instruction("copy", dest="v:i", args=[const(0)]), instruction("copy", dest="v:acc", args=[const(0)]), instruction("jump", target="H")),
            block("H", instruction("binary", dest="t:condition", operator="<", args=[var("v:i"), var("v:n")]), instruction("branch", args=[var("t:condition")], **{"then": "Body", "else": "Exit"})),
            block("Body", instruction("binary", dest="v:acc", operator="+", args=[var("v:acc"), var("v:i")]), instruction("binary", dest="v:i", operator="+", args=[var("v:i"), const(1)]), instruction("jump", target="H")),
            block("Exit", instruction("return", args=[var("v:acc")])),
        ], params=("n",))
        result = analyze(fn)
        expected_live = ["v:acc", "v:i", "v:n"]
        self.assertEqual(result["blocks"]["B0"]["live_in"], ["v:n"])
        self.assertEqual(result["blocks"]["B0"]["live_out"], expected_live)
        for label in ("H", "Body"):
            self.assertEqual(result["blocks"][label]["live_in"], expected_live)
            self.assertEqual(result["blocks"][label]["live_out"], expected_live)
        self.assertEqual(result["blocks"]["Exit"]["live_in"], ["v:acc"])
        self.assertEqual(result["cfg"]["H"]["predecessors"], ["B0", "Body"])
        self.assertEqual(result["blocks"]["Body"]["use"], ["v:acc", "v:i"])
        self.assert_valid_coloring(result)

    def test_two_parameters_dying_in_same_instruction_interfere(self):
        fn = function([block("B0", instruction("binary", dest="t:r", operator="+", args=[var("v:a"), var("v:b")]), instruction("return", args=[var("t:r")]))], params=("a", "b"))
        result = analyze(fn)
        self.assertEqual(result["interference"], {"t:r": [], "v:a": ["v:b"], "v:b": ["v:a"]})
        self.assertEqual(result["color_count"], 2)
        self.assert_valid_coloring(result)

    def test_simultaneous_outputs_interfere_even_if_one_is_dead(self):
        fn = function([block("B0", instruction("call", dests=["t:a", "t:b"], name="pair", args=[]), instruction("return", args=[var("t:a")]))])
        result = analyze(fn)
        self.assertEqual(result["interference"], {"t:a": ["t:b"], "t:b": ["t:a"]})
        self.assert_valid_coloring(result)

    def test_duplicate_branch_targets_are_one_cfg_edge(self):
        fn = function([block("B0", instruction("branch", args=[const(True)], **{"then": "Exit", "else": "Exit"})), block("Exit", instruction("return", args=[]))])
        cfg = build_cfg(fn)
        self.assertEqual(cfg["B0"]["successors"], ["Exit"])
        self.assertEqual(cfg["Exit"]["predecessors"], ["B0"])


if __name__ == "__main__":
    unittest.main()
