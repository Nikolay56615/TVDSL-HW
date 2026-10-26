"""Локальные повторы, копии значений и сохранение результатов и ошибок CSE."""

from copy import deepcopy
import itertools
import unittest

from HW4.funnyir import IRRuntimeError, compile_source, execute
from HW4.funnyir.cse import eliminate_common_expressions
from HW4.funnyir.optimize import optimize_module


def var(name):
    return {"var": name}


def const(value):
    return {"const": value}


def ins(op, **fields):
    return {"op": op, "pos": {"line": 7, "col": 3}, **fields}


def binary(dest, left="v:a", right="v:b", operator="+", **fields):
    return ins("binary", dest=dest, operator=operator,
               args=[var(left), var(right)], **fields)


def block(label, *instructions):
    return {"label": label, "instructions": list(instructions)}


def function(blocks, params=(("a", "int"), ("b", "int")), *, name="main", results=("int",)):
    return {
        "name": name,
        "params": [{"name": name, "type": type_} for name, type_ in params],
        "returns": [{"name": "r" + str(i), "type": type_} for i, type_ in enumerate(results)],
        "locals": [],
        "types": {"v:" + name: type_ for name, type_ in params},
        "entry": "B0",
        "blocks": blocks,
        "contracts": {"requires": None, "ensures": None, "invariants": []},
    }


def module(*functions):
    return {"version": 1, "functions": list(functions), "formulas": []}


def linear(*instructions, params=(("a", "int"), ("b", "int")), results=("int",)):
    return module(function([block("B0", *instructions)], params, results=results))


def instructions(mod):
    return [item for fn in mod["functions"] for bb in fn["blocks"] for item in bb["instructions"]]


def cse_only(mod):
    result = deepcopy(mod)
    for fn in result["functions"]:
        eliminate_common_expressions(fn)
    return result


class CSETests(unittest.TestCase):
    @staticmethod
    def outcome(mod, args, name="main"):
        try:
            return ("result", execute(mod, name, args, max_steps=10000))
        except IRRuntimeError as error:
            return ("error", error.code, error.pos)

    def compile(self, source):
        result = compile_source(source, optimize=False)
        self.assertTrue(result.ok, result.to_dict())
        return result.before

    def assert_preserved(self, original, args, expected=None, name="main"):
        before = self.outcome(original, args, name)
        self.assertEqual(self.outcome(cse_only(original), args, name), before)
        if expected is not None:
            self.assertEqual(before, expected)

    def test_pass_mutates_the_provided_function_and_returns_none(self):
        fn = function([block("B0", binary("t:x"), binary("t:y"), ins("return", args=[var("t:y")]))])
        self.assertIsNone(eliminate_common_expressions(fn))
        self.assertEqual(fn["blocks"][0]["instructions"][1], ins("copy", dest="t:y", args=[var("t:x")]))

    def test_repeated_source_expression_survives_new_temporary_names(self):
        original = self.compile("f(a:int,b:int) returns r:int uses x:int,y:int { x=a+b;y=a+b;r=x+y; }")
        after = cse_only(original)
        before_adds = [item for item in instructions(original) if item["op"] == "binary"]
        after_adds = [item for item in instructions(after) if item["op"] == "binary"]
        self.assertEqual(len(before_adds), 3)
        self.assertEqual(len(after_adds), 2)
        self.assertEqual(after_adds[0], before_adds[0])
        self.assert_preserved(original, [7, 4], ("result", [22]), "f")

    def test_unchanged_parameter_recopied_into_new_temporaries_matches(self):
        original = linear(
            ins("copy", dest="t:a1", args=[var("v:a")]),
            ins("copy", dest="t:b1", args=[var("v:b")]),
            binary("t:x", "t:a1", "t:b1"),
            ins("copy", dest="t:a2", args=[var("v:a")]),
            ins("copy", dest="t:b2", args=[var("v:b")]),
            binary("t:y", "t:a2", "t:b2"), ins("return", args=[var("t:y")]),
        )
        self.assertEqual(instructions(cse_only(original))[5]["op"], "copy")
        self.assert_preserved(original, [2, 5], ("result", [7]))

    def test_nested_expression_results_keep_their_value_numbers(self):
        original = linear(
            binary("t:x"), binary("t:scaled1", "t:x", "v:b", operator="*"),
            binary("t:y"), binary("t:scaled2", "t:y", "v:b", operator="*"),
            ins("return", args=[var("t:scaled2")]),
        )
        after = instructions(cse_only(original))
        self.assertEqual([item["op"] for item in after], ["binary", "binary", "copy", "copy", "return"])
        self.assert_preserved(original, [3, 4], ("result", [28]))

    def test_changed_operand_requires_a_new_computation(self):
        original = linear(binary("t:x"), ins("copy", dest="v:a", args=[const(30)]),
                          binary("t:y"), ins("return", args=[var("t:y")]))
        self.assertEqual(instructions(cse_only(original))[2]["op"], "binary")
        self.assert_preserved(original, [2, 5], ("result", [35]))

    def test_copy_is_a_snapshot_after_original_operand_changes(self):
        original = linear(
            ins("copy", dest="t:saved", args=[var("v:a")]), binary("t:x"),
            ins("copy", dest="v:a", args=[const(30)]), binary("t:y", "t:saved", "v:b"),
            ins("return", args=[var("t:y")]),
        )
        self.assertEqual(instructions(cse_only(original))[3]["op"], "copy")
        self.assert_preserved(original, [2, 5], ("result", [7]))

    def test_assignment_back_to_same_value_can_match(self):
        original = linear(
            ins("copy", dest="t:saved", args=[var("v:a")]), binary("t:x"),
            ins("copy", dest="v:a", args=[const(30)]),
            ins("copy", dest="v:a", args=[var("t:saved")]),
            binary("t:y"), ins("return", args=[var("t:y")]),
        )
        self.assertEqual(instructions(cse_only(original))[4]["op"], "copy")
        self.assert_preserved(original, [2, 5], ("result", [7]))

    def test_overwritten_result_without_backup_is_recomputed(self):
        original = linear(binary("t:x"), ins("copy", dest="t:x", args=[const(99)]),
                          binary("t:y"), ins("return", args=[var("t:y")]))
        self.assertEqual(instructions(cse_only(original))[2]["op"], "binary")
        self.assert_preserved(original, [2, 5], ("result", [7]))

    def test_overwritten_result_with_backup_reuses_current_holder(self):
        original = linear(
            binary("t:x"), ins("copy", dest="t:backup", args=[var("t:x")]),
            ins("copy", dest="t:x", args=[const(99)]), binary("t:y"),
            ins("return", args=[var("t:y")]),
        )
        self.assertEqual(instructions(cse_only(original))[3]["args"], [var("t:backup")])
        self.assert_preserved(original, [2, 5], ("result", [7]))

    def test_overwritten_backup_is_not_used(self):
        original = linear(
            binary("t:x"), ins("copy", dest="t:backup", args=[var("t:x")]),
            ins("copy", dest="t:x", args=[const(99)]),
            ins("copy", dest="t:backup", args=[const(100)]), binary("t:y"),
            ins("return", args=[var("t:y")]),
        )
        self.assertEqual(instructions(cse_only(original))[4]["op"], "binary")
        self.assert_preserved(original, [2, 5], ("result", [7]))

    def test_same_destination_can_copy_its_previous_result(self):
        original = linear(binary("t:x"), binary("t:x"), ins("return", args=[var("t:x")]))
        self.assertEqual(instructions(cse_only(original))[1], ins("copy", dest="t:x", args=[var("t:x")]))
        self.assert_preserved(original, [4, 8], ("result", [12]))

    def test_self_update_reads_old_operand_before_replacing_it(self):
        original = linear(binary("t:saved"), binary("v:a"), binary("t:y"),
                          ins("return", args=[var("t:y")]))
        after = instructions(cse_only(original))
        self.assertEqual(after[1]["args"], [var("t:saved")])
        self.assertEqual(after[2]["op"], "binary")
        self.assert_preserved(original, [2, 5], ("result", [12]))

    def test_first_self_update_does_not_confuse_old_and_new_operand(self):
        original = linear(binary("v:a"), binary("t:y"), ins("return", args=[var("t:y")]))
        self.assertEqual(instructions(cse_only(original))[1]["op"], "binary")
        self.assert_preserved(original, [2, 5], ("result", [12]))

    def test_all_pure_binary_operators_are_reused(self):
        for operator in ("+", "-", "*", "==", "!=", "<", "<=", ">", ">="):
            with self.subTest(operator=operator):
                original = linear(binary("t:x", operator=operator), binary("t:y", operator=operator),
                                  ins("return", args=[var("t:y")]))
                self.assertEqual(instructions(cse_only(original))[1]["op"], "copy")
                self.assert_preserved(original, [5, 9])

    def test_both_pure_unary_operators_are_reused(self):
        for operator, type_, value in (("-", "int", -2147483648), ("not", "bool", True)):
            with self.subTest(operator=operator):
                original = linear(ins("unary", dest="t:x", operator=operator, args=[var("v:a")]),
                                  ins("unary", dest="t:y", operator=operator, args=[var("v:a")]),
                                  ins("return", args=[var("t:y")]), params=(("a", type_),))
                self.assertEqual(instructions(cse_only(original))[1]["op"], "copy")
                self.assert_preserved(original, [value])

    def test_only_commutative_operators_accept_swapped_operands(self):
        for operator in ("+", "*", "==", "!=", "-", "<", "<=", ">", ">="):
            with self.subTest(operator=operator):
                original = linear(binary("t:x", operator=operator), binary("t:y", "v:b", "v:a", operator),
                                  ins("return", args=[var("t:y")]))
                expected = "copy" if operator in {"+", "*", "==", "!="} else "binary"
                self.assertEqual(instructions(cse_only(original))[1]["op"], expected)
                self.assert_preserved(original, [5, 9])

    def test_different_operators_do_not_match(self):
        original = linear(binary("t:x"), binary("t:y", operator="-"), ins("return", args=[var("t:y")]))
        self.assertEqual(instructions(cse_only(original))[1]["op"], "binary")
        self.assert_preserved(original, [2, 5], ("result", [-3]))

    def test_replacement_preserves_destination_position_and_extra_metadata(self):
        repeated = binary("t:y", pos={"line": 23, "col": 11}, note={"source": "second addition"})
        original = linear(binary("t:x"), repeated, ins("return", args=[var("t:y")]))
        expected = {**repeated, "op": "copy", "args": [var("t:x")]}
        del expected["operator"]
        self.assertEqual(instructions(cse_only(original))[1], expected)
        self.assertEqual(instructions(cse_only(original))[0], instructions(original)[0])

    def test_integer_and_boolean_constant_ids_are_distinct(self):
        for integer, boolean in ((0, False), (1, True)):
            with self.subTest(integer=integer):
                original = linear(ins("unary", dest="t:x", operator="not", args=[const(integer)]),
                                  ins("unary", dest="t:y", operator="not", args=[const(boolean)]),
                                  ins("return", args=[var("t:y")]), params=())
                self.assertEqual(instructions(cse_only(original))[1]["op"], "unary")

    def test_integer_constant_ids_use_signed_32_bit_values(self):
        original = linear(ins("unary", dest="t:x", operator="-", args=[const(4294967295)]),
                          ins("unary", dest="t:y", operator="-", args=[const(-1)]),
                          ins("return", args=[var("t:y")]), params=())
        self.assertEqual(instructions(cse_only(original))[1]["op"], "copy")
        self.assert_preserved(original, [], ("result", [1]))

    def test_new_literal_copies_keep_equal_normalized_values(self):
        original = linear(ins("copy", dest="t:c1", args=[const(4294967297)]),
                          binary("t:x", "v:a", "t:c1"),
                          ins("copy", dest="t:c2", args=[const(1)]),
                          binary("t:y", "v:a", "t:c2"),
                          ins("return", args=[var("t:y")]), params=(("a", "int"),))
        self.assertEqual(instructions(cse_only(original))[3]["op"], "copy")
        self.assert_preserved(original, [2147483647], ("result", [-2147483648]))

    def test_call_retained_and_all_output_operands_get_new_values(self):
        original = linear(binary("t:sum"),
                          ins("call", name="pair", dests=["v:a", "v:b"], args=[]),
                          binary("t:new"), ins("return", args=[var("t:new")]))
        original["functions"].append(function([block("B0", ins("return", args=[const(10), const(20)]))],
                                              (), name="pair", results=("int", "int")))
        after = instructions(cse_only(original))
        self.assertEqual(after[1], instructions(original)[1])
        self.assertEqual(after[2]["op"], "binary")
        self.assert_preserved(original, [2, 5], ("result", [30]))

    def test_call_invalidates_every_old_result_holder(self):
        original = linear(binary("t:x"), ins("copy", dest="t:backup", args=[var("t:x")]),
                          ins("call", name="pair", dests=["t:x", "t:backup"], args=[]),
                          binary("t:y"), ins("return", args=[var("t:y")]))
        original["functions"].append(function([block("B0", ins("return", args=[const(10), const(20)]))],
                                              (), name="pair", results=("int", "int")))
        self.assertEqual(instructions(cse_only(original))[3]["op"], "binary")
        self.assert_preserved(original, [2, 5], ("result", [7]))

    def test_call_can_leave_an_unmodified_result_available(self):
        original = linear(binary("t:x"), ins("call", name="value", dests=["t:other"], args=[]),
                          binary("t:y"), ins("return", args=[var("t:y")]))
        original["functions"].append(function([block("B0", ins("return", args=[const(10)]))], (), name="value"))
        self.assertEqual(instructions(cse_only(original))[2]["op"], "copy")
        self.assert_preserved(original, [2, 5], ("result", [7]))

    def test_call_with_dest_and_dests_invalidates_both_fields(self):
        original = linear(binary("t:x"), ins("copy", dest="t:backup", args=[var("t:x")]),
                          ins("call", name="opaque", dest="t:x", dests=["t:backup"], args=[]),
                          binary("t:y"), ins("return", args=[var("t:y")]))
        self.assertEqual(instructions(cse_only(original))[3]["op"], "binary")

    def test_trapping_and_opaque_instructions_are_never_replaced(self):
        candidates = [
            ins("binary", dest="t:x", operator="/", args=[var("v:a"), var("v:b")]),
            ins("get", dest="t:x", args=[var("v:array"), const(0)]),
            ins("set", dest="t:x", args=[var("v:array"), const(0), const(2)]),
            ins("length", dest="t:x", args=[var("v:array")]),
            ins("call", name="callee", dests=["t:x"], args=[var("v:a")]),
            ins("spec", kind="assert", predicate={"kind": "Bool", "value": False}, args=[]),
            ins("binary", dest="t:x", operator="and", args=[const(True), const(False)]),
        ]
        for candidate in candidates:
            with self.subTest(op=candidate["op"], operator=candidate.get("operator")):
                second = deepcopy(candidate)
                second["pos"] = {"line": 8, "col": 9}
                if "dest" in second:
                    second["dest"] = "t:y"
                if "dests" in second:
                    second["dests"] = ["t:y"]
                original = linear(candidate, second, ins("return", args=[const(0)]))
                self.assertEqual(cse_only(original), original)

    def test_no_reuse_between_adjacent_blocks(self):
        original = module(function([
            block("B0", binary("t:x"), ins("jump", target="Next")),
            block("Next", binary("t:y"), ins("return", args=[var("t:y")])),
        ]))
        self.assertEqual(cse_only(original), original)
        self.assert_preserved(original, [2, 5], ("result", [7]))

    def test_join_does_not_assume_expression_was_computed_on_both_paths(self):
        original = module(function([
            block("B0", ins("branch", args=[var("v:condition")], **{"then": "Yes", "else": "No"})),
            block("Yes", binary("t:x"), ins("jump", target="Join")),
            block("No", ins("jump", target="Join")),
            block("Join", binary("t:y"), ins("return", args=[var("t:y")]))
        ], params=(("a", "int"), ("b", "int"), ("condition", "bool"))))
        self.assertEqual(cse_only(original), original)
        for condition in (False, True):
            self.assert_preserved(original, [2, 5, condition], ("result", [7]))

    def test_loop_body_and_exit_have_independent_caches(self):
        original = self.compile("f(n:int) returns r:int uses i:int,x:int { i=0;r=0;while(i<n) { x=i+1;r=r+x;i=i+1; } r=i+1; }")
        after = cse_only(original)
        self.assertLess(len([item for item in instructions(after) if item["op"] == "binary"]),
                        len([item for item in instructions(original) if item["op"] == "binary"]))
        exit_block = after["functions"][0]["blocks"][-1]
        self.assertTrue(any(item["op"] == "binary" and item["operator"] == "+" for item in exit_block["instructions"]))
        for n in (0, 1, 8):
            self.assert_preserved(original, [n], ("result", [n + 1]), "f")

    def test_uninitialized_read_still_reports_the_first_original_position(self):
        first = binary("t:dead", "v:missing", "v:b", pos={"line": 11, "col": 4})
        second = binary("t:again", "v:missing", "v:b", pos={"line": 12, "col": 9})
        original = linear(first, second, ins("return", args=[const(0)]), params=(("b", "int"),))
        self.assert_preserved(original, [3], ("error", "uninitialized", {"line": 11, "col": 4}))
        self.assertEqual(instructions(cse_only(original))[0], first)

    def test_optimize_module_keeps_all_input_data_independent(self):
        original = self.compile("p(x:int)=>x>=0; f(a:int,b:int) requires p(a) returns r:int ensures p(r) uses x:int,y:int { assert p(a); x=a+b;y=a+b;r=x+y; }")
        original["extra"] = {"notes": ["preserve source"]}
        saved = deepcopy(original)
        after = optimize_module(original, constants=False, simplify=False, cse=True, dce=False)
        self.assertEqual(original, saved)
        self.assertEqual(after["formulas"], original["formulas"])
        self.assertEqual(after["functions"][0]["contracts"], original["functions"][0]["contracts"])
        after["extra"]["notes"].append("new")
        after["formulas"][0]["name"] = "changed"
        after["functions"][0]["contracts"]["requires"]["name"] = "changed"
        self.assertEqual(original, saved)

    def test_disabling_cse_keeps_repeated_computations(self):
        original = linear(binary("t:x"), binary("t:y"), ins("return", args=[var("t:y")]))
        after = optimize_module(original, constants=False, simplify=False, cse=False, dce=False)
        self.assertEqual(after, original)
        enabled = optimize_module(original, constants=False, simplify=False, cse=True, dce=False)
        self.assertEqual(instructions(enabled)[1]["op"], "copy")

    def test_all_sixteen_flag_combinations_preserve_outputs_and_trap_positions(self):
        cases = [
            ("f(a:int,b:int) returns r:int uses x:int,y:int { x=a+b;y=a+b;r=x+y; }", [2147483647, 1]),
            ("f(a:int,b:int) returns r:int uses m:int,s:int,x:int,y:int { m=a;s=m;x=m+b;m=m+1;y=s+b;r=x+y; }", [5, 7]),
            ("f(n:int) returns r:int uses i:int,x:int,y:int { i=0;r=0;while(i<n) { x=i+1;y=i+1;r=r+x+y;i=i+1; } }", [4]),
            ("f(c:int) returns r:int uses x:int,y:int { if(c>0) x=c+1; y=c+1;r=y; }", [-1]),
            ("f() returns r:int uses x:int,y:int,z:int {\n y=x+1;\n z=x+1;r=0; }", []),
            ("f(a:int) returns r:int uses x:int,y:int {\n x=a/0;\n y=a/0;r=0; }", [3]),
            ("f(a:int[]) returns r:int uses x:int,y:int {\n x=a[2];\n y=a[2];r=0; }", [[1]]),
            ("bad() returns r:int {\n r=1/0; } f() returns r:int uses x:int,y:int { x=bad();y=bad();r=0; }", []),
        ]
        for source, args in cases:
            original = self.compile(source)
            expected = self.outcome(original, args, "f")
            for constants, simplify, cse, dce in itertools.product((False, True), repeat=4):
                flags = dict(constants=constants, simplify=simplify, cse=cse, dce=dce)
                with self.subTest(source=source, **flags):
                    after = optimize_module(original, **flags)
                    self.assertEqual(self.outcome(after, args, "f"), expected)


if __name__ == "__main__":
    unittest.main()
