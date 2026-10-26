"""Независимые проверки lowering: CFG, порядок чтений, AST и спецификации."""

from copy import deepcopy
import json
import unittest

from HW3.funnytypes import check
from HW4.funnyir.interpreter import IRRuntimeError, execute
from HW4.funnyir.ir import (TERMINATORS, cfg_dot, definitions, format_ir,
                           interference_dot, successors, uses)
from HW4.funnyir.lower import lower


def instructions(function):
    return [instruction for block in function["blocks"]
            for instruction in block["instructions"]]


class LoweringTests(unittest.TestCase):
    def typed(self, source):
        result = check(source)
        self.assertTrue(result.ok, result.to_dict())
        return result.ast

    def module(self, source):
        return lower(self.typed(source))

    def test_three_address_order_types_and_implicit_return(self):
        module = self.module("f(x:int) returns r:int uses t0 { t0=x+2*3; r=t0; }")
        function = module["functions"][0]
        code = instructions(function)
        self.assertEqual([item["op"] for item in code],
                         ["copy", "copy", "copy", "binary", "binary", "copy", "copy", "copy", "return"])
        self.assertEqual([item.get("operator") for item in code if item["op"] == "binary"], ["*", "+"])
        self.assertEqual(code[0]["args"], [{"var": "v:x"}])
        self.assertEqual(code[-1]["args"], [{"var": "v:r"}])
        self.assertEqual(function["locals"], [{"name": "t0", "type": "int"}])
        self.assertIn("v:t0", function["types"])
        self.assertIn("t:0", function["types"])
        self.assertEqual(execute(module, "f", [4]), [10])

    def test_all_blocks_have_one_final_terminator_in_nested_control_flow(self):
        module = self.module("""f(n:int) returns r:int uses i:int {
            i=0; r=0;
            while(i<n and not i<0) {
                if(i==2 or i==3) r=r+2; else { if(i>3) r=r+3; }
                i=i+1;
            }
        }""")
        function = module["functions"][0]
        labels = {block["label"] for block in function["blocks"]}
        self.assertEqual(len(labels), len(function["blocks"]))
        for block in function["blocks"]:
            with self.subTest(block=block["label"]):
                self.assertTrue(block["instructions"])
                self.assertIn(block["instructions"][-1]["op"], TERMINATORS)
                self.assertFalse(any(item["op"] in TERMINATORS for item in block["instructions"][:-1]))
                self.assertTrue(set(successors(block)) <= labels)
        self.assertEqual(execute(module, "f", [5]), [7])

    def test_short_circuit_skips_errors_and_negation_swaps_branches(self):
        conditions = [
            ("false and 1/0>0", 20),
            ("true or a[100]>0", 10),
            ("false -> 1/0>0", 10),
            ("true -> false", 20),
            ("not (true or a[100]>0)", 20),
            ("not (false and 1/0>0)", 10),
        ]
        for condition, expected in conditions:
            with self.subTest(condition=condition):
                module = self.module("f(a:int[]) returns r:int { if(%s) r=10; else r=20; }" % condition)
                self.assertEqual(execute(module, "f", [[]]), [expected])
                self.assertFalse(any(item.get("operator") in {"and", "or", "->", "not"}
                                     for item in instructions(module["functions"][0])))

    def test_short_circuit_right_side_is_evaluated_when_required(self):
        for condition in ("true and 1/0>0", "false or 1/0>0", "true -> 1/0>0"):
            with self.subTest(condition=condition):
                module = self.module("f() returns r:int { if(%s) r=1; else r=2; }" % condition)
                with self.assertRaises(IRRuntimeError) as caught:
                    execute(module, "f")
                self.assertEqual(caught.exception.code, "division_by_zero")

    def test_call_results_are_temporary_before_any_tuple_target_write(self):
        module = self.module("""f() returns r:int,s:int { r=7; s=11; r,s=pair(s,r); }
            pair(x:int,y:int) returns a:int,b:int { a=x; b=y; }""")
        function = module["functions"][0]
        code = instructions(function)
        call_index = next(index for index, item in enumerate(code) if item["op"] == "call")
        call = code[call_index]
        self.assertEqual(len(call["dests"]), 2)
        self.assertTrue(all(name.startswith("t:") for name in call["dests"]))
        self.assertEqual([item["args"] for item in code[call_index - 2:call_index]],
                         [[{"var": "v:s"}], [{"var": "v:r"}]])
        self.assertEqual([item["dest"] for item in code[call_index + 1:call_index + 3]], ["v:r", "v:s"])
        self.assertEqual(execute(module, "f"), [11, 7])

    def test_nested_call_arguments_and_failure_order_are_left_to_right(self):
        module = self.module("""f() returns r:int uses unset:int { r=add(unset,1/0); }
            add(x:int,y:int) returns r:int { r=x+y; }""")
        with self.assertRaises(IRRuntimeError) as caught:
            execute(module, "f")
        self.assertEqual(caught.exception.code, "uninitialized")
        module = self.module("""f() returns r:int uses x:int { x=4; r=add(one(x),one(2)); }
            add(x:int,y:int) returns r:int { r=x+y; }
            one(x:int) returns r:int { r=x+1; }""")
        calls = [item["name"] for item in instructions(module["functions"][0]) if item["op"] == "call"]
        self.assertEqual(calls, ["one", "one", "add"])
        self.assertEqual(execute(module, "f"), [8])

    def test_array_update_length_and_copy_have_value_semantics(self):
        module = self.module("""f(a:int[]) returns b:int[],r:int uses saved {
            saved=a; b=saved; b[0]=b[0]+10; r=length(b)+saved[0];
        }""")
        arguments = [[2, 3]]
        self.assertEqual(execute(module, "f", arguments), [[12, 3], 4])
        self.assertEqual(arguments, [[2, 3]])
        ops = {item["op"] for item in instructions(module["functions"][0])}
        self.assertTrue({"get", "set", "length"} <= ops)
        self.assertEqual(module["functions"][0]["locals"], [{"name": "saved", "type": "int[]"}])

    def test_late_reference_and_recursion_need_no_early_body_resolution(self):
        module = self.module("""f(n:int) returns r:int { r=fact(n); }
            fact(n:int) returns r:int { if(n<=1) r=1; else r=n*fact(n-1); }""")
        self.assertEqual(execute(module, "f", [5]), [120])

    def test_source_positions_are_original_crlf_positions(self):
        module = self.module("f(x:int,a:int[]) returns r:int {\r\n  r=x/0;\r\n  r=a[2];\r\n}")
        code = instructions(module["functions"][0])
        division = next(item for item in code if item.get("operator") == "/")
        access = next(item for item in code if item["op"] == "get")
        self.assertEqual(division["pos"], {"line": 2, "col": 6})
        self.assertEqual(access["pos"], {"line": 3, "col": 6})
        self.assertEqual(code[0]["pos"], {"line": 2, "col": 5})
        self.assertTrue(all(set(item["pos"]) == {"line", "col"} for item in code))

    def test_contracts_formulas_and_invariants_are_ast_metadata_only(self):
        source = """positive(a:int[]) => forall(i:int | i>=0 -> a[i]>0);
            f(a:int[]) requires positive(a) returns r:int ensures r<0 uses i:int {
                assert forall(j:int | j>=0 -> a[j]>0);
                assume false;
                i=0; r=0;
                while(i<length(a)) invariant i>=0 { r=r+a[i]; i=i+1; }
            }"""
        ast = self.typed(source)
        module = lower(ast)
        function = module["functions"][0]
        declaration = ast["declarations"][1]
        self.assertEqual(module["formulas"], [ast["declarations"][0]])
        self.assertEqual(function["contracts"]["requires"], declaration["requires"])
        self.assertEqual(function["contracts"]["ensures"], declaration["ensures"])
        invariant = function["contracts"]["invariants"][0]
        header = next(block for block in function["blocks"] if block["label"] == invariant["block"])
        self.assertEqual(header["instructions"][-1]["op"], "branch")
        specs = [item for item in instructions(function) if item["op"] == "spec"]
        self.assertEqual([item["kind"] for item in specs], ["assert", "assume"])
        self.assertEqual(specs[0]["predicate"], declaration["body"]["statements"][0]["predicate"])
        self.assertEqual(specs[0]["args"], [])
        self.assertEqual(uses(specs[0]), {"v:a"})
        self.assertEqual(execute(module, "f", [[1, -2]]), [-1])

    def test_lower_is_deterministic_json_and_does_not_alias_ast(self):
        ast = self.typed("p(x:int)=>x>0; f(x:int) requires p(x) returns r:int { assert x>0; r=x; }")
        snapshot = deepcopy(ast)
        first, second = lower(ast), lower(ast)
        self.assertEqual(first, second)
        self.assertEqual(json.loads(json.dumps(first)), first)
        self.assertEqual(ast, snapshot)
        first["formulas"][0]["predicate"]["left"]["name"] = "changed"
        first["functions"][0]["contracts"]["requires"]["name"] = "changed"
        spec = next(item for item in instructions(first["functions"][0]) if item["op"] == "spec")
        spec["predicate"]["left"]["name"] = "changed"
        first["functions"][0]["blocks"][0]["instructions"][0]["pos"]["line"] = 999
        self.assertEqual(ast, snapshot)
        self.assertEqual(lower(ast), second)


class IRHelpersTests(unittest.TestCase):
    def test_dependency_helpers_separate_literals_names_and_call_results(self):
        instruction = {"op": "call", "dests": ["t:1", "t:2"], "name": "f",
                       "args": [{"var": "v:x"}, {"const": 2}, {"var": "v:x"}]}
        self.assertEqual(uses(instruction), {"v:x"})
        self.assertEqual(definitions(instruction), {"t:1", "t:2"})
        self.assertEqual(definitions({"op": "copy", "dest": "v:x", "args": []}), {"v:x"})
        self.assertEqual(definitions({"op": "return", "args": []}), set())

    def test_nested_quantifiers_hide_only_bound_names(self):
        checked = check("f(a:int[],n:int) returns r:int { assert forall(i:int | exists(j:int | a[i]+j>n)); r=0; }")
        self.assertTrue(checked.ok, checked.to_dict())
        spec = instructions(lower(checked.ast)["functions"][0])[0]
        self.assertEqual(uses(spec), {"v:a", "v:n"})
        self.assertEqual(definitions(spec), set())

    def test_successors_read_terminators_only_and_deduplicate(self):
        block = {"label": "B0", "instructions": [{"op": "branch", "then": "B1", "else": "B1"}]}
        self.assertEqual(successors(block), ["B1"])
        self.assertEqual(successors({"instructions": [{"op": "return", "args": []}]}), [])
        self.assertEqual(successors({"instructions": []}), [])

    def test_text_and_dot_outputs_are_deterministic_and_do_not_mutate(self):
        checked = check("f(x:int) returns r:int { if(x>0) r=x; else r=0; }")
        self.assertTrue(checked.ok, checked.to_dict())
        module = lower(checked.ast)
        snapshot = deepcopy(module)
        function = module["functions"][0]
        cfg = {block["label"]: {"successors": successors(block), "reachable": True}
               for block in function["blocks"]}
        text = format_ir(module)
        self.assertIn("function f(x:int) returns r:int", text)
        self.assertIn("branch", text)
        self.assertIn("return v:r", text)
        self.assertEqual(text, format_ir(module))
        dot = cfg_dot(function, cfg)
        self.assertIn('digraph "cfg_f"', dot)
        self.assertIn('"B0" -> "B1";', dot)
        graph = {"t:0": ["v:x"], "v:x": ["t:0"]}
        colors = {"t:0": 0, "v:x": 1}
        colored = interference_dot(function, graph, colors)
        self.assertEqual(colored.count('"t:0" -- "v:x";'), 1)
        self.assertIn("color=1", colored)
        self.assertEqual(module, snapshot)


if __name__ == "__main__":
    unittest.main()
