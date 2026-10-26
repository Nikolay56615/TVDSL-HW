"""Проверка проходов отдельно и сохранения результатов/ошибок исполнения."""

from copy import deepcopy
import itertools
import unittest

from HW4.funnyir import IRRuntimeError, execute
from HW4.funnyir.optimize import optimize_module


def var(name):
    return {"var": name}


def const(value):
    return {"const": value}


def instruction(op, **fields):
    return {"op": op, "pos": {"line": 7, "col": 3}, **fields}


def block(label, *instructions):
    return {"label": label, "instructions": list(instructions)}


def function(blocks, params=(), *, name="main", result_types=("int",)):
    return {
        "name": name,
        "params": [{"name": name, "type": type_} for name, type_ in params],
        "returns": [{"name": "result" + str(index), "type": type_} for index, type_ in enumerate(result_types)],
        "locals": [],
        "types": {"v:" + name: type_ for name, type_ in params},
        "entry": "B0",
        "blocks": blocks,
        "contracts": {"requires": None, "ensures": None, "invariants": []},
    }


def module(*functions):
    return {"version": 1, "functions": list(functions), "formulas": []}


def linear(*instructions, params=()):
    return module(function([block("B0", *instructions)], params))


def all_instructions(mod):
    return [ins for fn in mod["functions"] for item in fn["blocks"] for ins in item["instructions"]]


class OptimizationTests(unittest.TestCase):
    @staticmethod
    def outcome(mod, args):
        try:
            return ("result", execute(mod, arguments=args, max_steps=3000))
        except IRRuntimeError as error:
            return ("error", error.code, error.pos)

    def assert_preserved(self, original, args, expected=None, **flags):
        before = self.outcome(original, args)
        after = self.outcome(optimize_module(original, **flags), args)
        self.assertEqual(after, before)
        if expected is not None:
            self.assertEqual(before, expected)

    def test_local_constant_environment_survives_redefinition(self):
        original = linear(
            instruction("copy", dest="t:a", args=[const(2)]),
            instruction("copy", dest="t:b", args=[var("t:a")]),
            instruction("copy", dest="t:a", args=[const(7)]),
            instruction("binary", dest="t:r", operator="+", args=[var("t:b"), var("t:a")]),
            instruction("return", args=[var("t:r")]),
        )
        result = optimize_module(original)
        self.assertEqual(all_instructions(result), [instruction("return", args=[const(9)])])
        self.assert_preserved(original, [], ("result", [9]))

    def test_unknown_copy_is_not_a_mutable_alias(self):
        original = linear(
            instruction("copy", dest="t:a", args=[var("v:p")]),
            instruction("copy", dest="t:b", args=[var("t:a")]),
            instruction("copy", dest="t:a", args=[const(7)]),
            instruction("binary", dest="t:r", operator="+", args=[var("t:b"), var("t:a")]),
            instruction("return", args=[var("t:r")]), params=(("p", "int"),),
        )
        for value in (-12, 0, 5, 2147483647):
            self.assert_preserved(original, [value])
        self.assertEqual(execute(optimize_module(original), arguments=[5]), [12])

    def test_constants_do_not_flow_between_blocks(self):
        original = module(function([
            block("B0", instruction("copy", dest="v:x", args=[const(1)]), instruction("jump", target="Next")),
            block("Next", instruction("binary", dest="t:r", operator="+", args=[var("v:x"), const(2)]), instruction("return", args=[var("t:r")])),
        ]))
        after = optimize_module(original, simplify=False, dce=False)
        self.assertEqual(after["functions"][0]["blocks"][1]["instructions"][0]["args"], [var("v:x"), const(2)])
        self.assert_preserved(original, [], ("result", [3]))

    def test_writing_unknown_value_kills_constant(self):
        original = linear(
            instruction("copy", dest="t:a", args=[const(3)]),
            instruction("copy", dest="t:a", args=[var("v:p")]),
            instruction("binary", dest="t:r", operator="+", args=[var("t:a"), const(1)]),
            instruction("return", args=[var("t:r")]), params=(("p", "int"),),
        )
        after = optimize_module(original, simplify=False, dce=False)
        self.assertEqual(all_instructions(after)[2]["args"], [var("t:a"), const(1)])
        self.assert_preserved(original, [10], ("result", [11]))

    def test_call_kills_all_output_constants_and_is_retained(self):
        original = linear(
            instruction("copy", dest="t:a", args=[const(3)]),
            instruction("copy", dest="t:b", args=[const(4)]),
            instruction("call", dests=["t:a", "t:b"], name="pair", args=[]),
            instruction("binary", dest="t:r", operator="+", args=[var("t:a"), var("t:b")]),
            instruction("return", args=[var("t:r")]),
        )
        original["functions"].append(function([block("B0", instruction("return", args=[const(10), const(20)]))], name="pair", result_types=("int", "int")))
        after = optimize_module(original, dce=False)
        self.assertEqual(after["functions"][0]["blocks"][0]["instructions"][3]["args"], [var("t:a"), var("t:b")])
        self.assert_preserved(original, [], ("result", [30]))

    def test_folding_uses_int32_and_truncation_toward_zero(self):
        for operator, left, right, expected in [
            ("+", 2147483647, 1, -2147483648),
            ("*", 65536, 65536, 0),
            ("/", -7, 3, -2),
            ("/", 7, -3, -2),
            ("/", -2147483648, -1, -2147483648),
            ("<", 4294967295, 1, True),
        ]:
            with self.subTest(operator=operator, left=left, right=right):
                original = linear(instruction("binary", dest="t:r", operator=operator, args=[const(left), const(right)]), instruction("return", args=[var("t:r")]))
                self.assertEqual(all_instructions(optimize_module(original)), [instruction("return", args=[const(expected)])])
                self.assert_preserved(original, [], ("result", [expected]))
        for operator, value, expected in [("-", -2147483648, -2147483648), ("not", False, True)]:
            original = linear(instruction("unary", dest="t:r", operator=operator, args=[const(value)]), instruction("return", args=[var("t:r")]))
            self.assert_preserved(original, [], ("result", [expected]))

    def test_safe_identities_become_copies_without_folding(self):
        for operator, args in [
            ("+", [var("v:p"), const(0)]), ("+", [const(0), var("v:p")]),
            ("-", [var("v:p"), const(0)]), ("*", [var("v:p"), const(1)]),
            ("*", [const(1), var("v:p")]), ("/", [var("v:p"), const(1)]),
        ]:
            with self.subTest(operator=operator, args=args):
                original = linear(instruction("binary", dest="t:r", operator=operator, args=args), instruction("return", args=[var("t:r")]), params=(("p", "int"),))
                after = optimize_module(original, constants=False, dce=False)
                self.assertEqual(all_instructions(after)[0], instruction("copy", dest="t:r", args=[var("v:p")]))
                self.assert_preserved(original, [-2147483648], constants=False)

    def test_unsafe_identities_remain_operations(self):
        for operator, args in [
            ("*", [var("v:missing"), const(0)]),
            ("*", [const(0), var("v:missing")]),
            ("/", [const(0), var("v:missing")]),
            ("/", [var("v:missing"), var("v:missing")]),
        ]:
            with self.subTest(operator=operator, args=args):
                original = linear(instruction("binary", dest="t:dead", operator=operator, args=args), instruction("return", args=[const(0)]))
                self.assertEqual(all_instructions(optimize_module(original))[0]["op"], "binary")
                self.assert_preserved(original, [], ("error", "uninitialized", {"line": 7, "col": 3}))

    def test_dce_removes_dead_chain_across_blocks(self):
        original = module(function([
            block("B0", instruction("copy", dest="t:a", args=[const(1)]), instruction("jump", target="Next")),
            block("Next", instruction("binary", dest="t:b", operator="+", args=[var("t:a"), const(2)]), instruction("return", args=[const(4)])),
        ]))
        after = optimize_module(original, constants=False, simplify=False)
        self.assertEqual([item["op"] for item in all_instructions(after)], ["jump", "return"])
        self.assert_preserved(original, [], ("result", [4]), constants=False, simplify=False)

    def test_dce_keeps_uninitialized_pure_read_and_its_position(self):
        original = linear(instruction("unary", dest="t:dead", operator="-", args=[var("v:missing")]), instruction("return", args=[const(4)]))
        self.assertEqual(len(all_instructions(optimize_module(original))), 2)
        self.assert_preserved(original, [], ("error", "uninitialized", {"line": 7, "col": 3}))

    def test_dce_meets_definitions_by_intersection_at_join(self):
        original = module(function([
            block("B0", instruction("branch", args=[var("v:p")], **{"then": "Yes", "else": "No"})),
            block("Yes", instruction("copy", dest="v:x", args=[const(1)]), instruction("jump", target="Join")),
            block("No", instruction("jump", target="Join")),
            block("Join", instruction("binary", dest="t:dead", operator="+", args=[var("v:x"), const(0)]), instruction("return", args=[const(0)])),
        ], params=(("p", "bool"),)))
        self.assert_preserved(original, [True], ("result", [0]))
        self.assert_preserved(original, [False], ("error", "uninitialized", {"line": 7, "col": 3}))
        self.assertEqual(optimize_module(original)["functions"][0]["blocks"][3]["instructions"][0]["args"], [var("v:x")])

    def test_dce_cannot_assume_a_loop_body_has_run(self):
        original = module(function([
            block("B0", instruction("copy", dest="v:i", args=[const(0)]), instruction("jump", target="Head")),
            block("Head", instruction("binary", dest="t:condition", operator="<", args=[var("v:i"), var("v:n")]), instruction("branch", args=[var("t:condition")], **{"then": "Body", "else": "Exit"})),
            block("Body", instruction("copy", dest="v:x", args=[const(10)]), instruction("binary", dest="v:i", operator="+", args=[var("v:i"), const(1)]), instruction("jump", target="Head")),
            block("Exit", instruction("binary", dest="t:dead", operator="+", args=[var("v:x"), const(1)]), instruction("return", args=[const(0)])),
        ], params=(("n", "int"),)))
        self.assert_preserved(original, [0], ("error", "uninitialized", {"line": 7, "col": 3}))
        self.assert_preserved(original, [3], ("result", [0]))

    def test_dce_removes_dead_read_defined_on_every_join_path(self):
        original = module(function([
            block("B0", instruction("branch", args=[var("v:p")], **{"then": "Yes", "else": "No"})),
            block("Yes", instruction("copy", dest="v:x", args=[const(1)]), instruction("jump", target="Join")),
            block("No", instruction("copy", dest="v:x", args=[const(2)]), instruction("jump", target="Join")),
            block("Join", instruction("binary", dest="t:dead", operator="+", args=[var("v:x"), const(0)]), instruction("return", args=[const(0)])),
        ], params=(("p", "bool"),)))
        after = optimize_module(original, constants=False, simplify=False)
        self.assertFalse(any(item["op"] in {"copy", "binary"} for item in all_instructions(after)))
        for arg in (True, False):
            self.assert_preserved(original, [arg], ("result", [0]))

    def test_dce_preserves_trapping_and_array_operations(self):
        programs = [
            (linear(instruction("binary", dest="t:dead", operator="/", args=[const(1), const(0)]), instruction("return", args=[const(0)])), [], "division_by_zero"),
            (linear(instruction("binary", dest="t:dead", operator="/", args=[const(0), var("v:p")]), instruction("return", args=[const(0)]), params=(("p", "int"),)), [0], "division_by_zero"),
            (linear(instruction("get", dest="t:dead", args=[var("v:a"), const(-1)]), instruction("return", args=[const(0)]), params=(("a", "int[]"),)), [[1]], "array_bounds"),
            (linear(instruction("set", dest="t:dead", args=[var("v:a"), const(9), const(1)]), instruction("return", args=[const(0)]), params=(("a", "int[]"),)), [[1]], "array_bounds"),
            (linear(instruction("length", dest="t:dead", args=[var("v:a")]), instruction("return", args=[const(0)]), params=(("a", "int[]"),)), [[]], None),
        ]
        for original, args, error in programs:
            with self.subTest(op=all_instructions(original)[0]["op"], error=error):
                self.assertEqual(len(all_instructions(optimize_module(original))), 2)
                expected = ("error", error, {"line": 7, "col": 3}) if error else ("result", [0])
                self.assert_preserved(original, args, expected)

    def test_dead_call_keeps_callee_error(self):
        original = linear(instruction("call", dests=["t:dead"], name="bad", args=[]), instruction("return", args=[const(0)]))
        original["functions"].append(function([block("B0", instruction("binary", dest="t:r", operator="/", args=[const(1), const(0)]), instruction("return", args=[var("t:r")]))], name="bad"))
        self.assertTrue(any(item["op"] == "call" for item in all_instructions(optimize_module(original))))
        self.assert_preserved(original, [], ("error", "division_by_zero", {"line": 7, "col": 3}))

    def test_spec_formulas_contracts_and_input_are_preserved(self):
        predicate = {"kind": "Name", "name": "x", "inferred_type": "int"}
        original = linear(instruction("copy", dest="v:x", args=[const(5)]), instruction("spec", kind="assert", predicate=predicate, args=[]), instruction("return", args=[const(0)]))
        original["formulas"] = [{"name": "f", "predicate": deepcopy(predicate)}]
        original["functions"][0]["contracts"]["requires"] = deepcopy(predicate)
        saved = deepcopy(original)
        after = optimize_module(original)
        self.assertEqual(original, saved)
        self.assertIsNot(after, original)
        self.assertEqual(after["formulas"], original["formulas"])
        self.assertEqual(after["functions"][0]["contracts"], original["functions"][0]["contracts"])
        self.assertIn(instruction("spec", kind="assert", predicate=predicate, args=[]), all_instructions(after))
        after["formulas"][0]["predicate"]["name"] = "changed"
        self.assertEqual(original, saved)

    def test_every_flag_combination_preserves_semantics(self):
        original = linear(
            instruction("copy", dest="t:constant", args=[const(10)]),
            instruction("binary", dest="t:dead", operator="*", args=[var("v:p"), const(1)]),
            instruction("binary", dest="t:first", operator="+", args=[var("v:p"), var("t:constant")]),
            instruction("binary", dest="t:r", operator="+", args=[var("v:p"), var("t:constant")]),
            instruction("return", args=[var("t:r")]), params=(("p", "int"),),
        )
        for constants, simplify, cse, dce in itertools.product((False, True), repeat=4):
            flags = dict(constants=constants, simplify=simplify, cse=cse, dce=dce)
            with self.subTest(**flags):
                self.assert_preserved(original, [2147483647], **flags)
        self.assertEqual(optimize_module(original, constants=False, simplify=False, cse=False, dce=False), original)


if __name__ == "__main__":
    unittest.main()
