"""Исполнение исходного и оптимизированного IR с независимыми эталонами."""

from copy import deepcopy
import unittest

from HW3.funnytypes import check
from HW4.funnyir import compile_ast, compile_source, execute, IRRuntimeError
from HW4.funnyir.operations import evaluate_binary, evaluate_unary, i32


class RuntimeTests(unittest.TestCase):
    def compile(self, source, **options):
        result = compile_source(source, **options)
        self.assertTrue(result.ok, result.to_dict())
        return result

    def values(self, source, expected, args=None, name="f", **options):
        result = self.compile(source, **options)
        for version in (result.before, result.after):
            with self.subTest(version="before" if version is result.before else "after"):
                self.assertEqual(execute(version, name, args), expected)
        return result

    def trap(self, source, code, args=None, name="f", **limits):
        result = self.compile(source)
        for version in (result.before, result.after):
            with self.subTest(version="before" if version is result.before else "after"):
                with self.assertRaises(IRRuntimeError) as caught:
                    execute(version, name, args, **limits)
                self.assertEqual(caught.exception.code, code)
                self.assertGreaterEqual(caught.exception.pos["line"], 1)
                self.assertGreaterEqual(caught.exception.pos["col"], 1)

    def test_arithmetic_matches_hand_calculated_result(self):
        self.values("f(x:int) returns r:int { r=-(x+2)*3+20/4; }", [-10], [3])

    def test_integer_overflow_matches_jvm(self):
        for expression, expected in (("2147483647+1", -2147483648),
                                     ("2147483648-1", 2147483647),
                                     ("65536*65536", 0),
                                     ("-2147483648", -2147483648),
                                     ("2147483648/-1", -2147483648)):
            with self.subTest(expression=expression):
                self.values("f() returns r:int { r=" + expression + "; }", [expected])

    def test_division_rounds_toward_zero_without_floats(self):
        for left, right, expected in ((-7, 3, -2), (7, -3, -2), (-7, -3, 2), (7, 3, 2)):
            with self.subTest(left=left, right=right):
                self.values("f(x:int,y:int) returns r:int { r=x/y; }", [expected], [left, right])

    def test_input_and_literal_normalization_are_the_same(self):
        self.values("f(x:int) returns r:int { r=x+4294967296; }", [0], [4294967296])
        self.values("f(a:int[]) returns r:int { r=a[0]; }", [-2147483648], [[2147483648]])

    def test_comparison_after_wrapped_arithmetic(self):
        self.values("f() returns r:int { if(2147483647+1<0) r=1; else r=0; }", [1])

    def test_all_comparisons_and_nested_if(self):
        source = "f(x:int) returns r:int { r=0; if(x>=0) { if(x!=0) r=1; else r=2; } else if(x<=-2) r=3; else r=4; }"
        for value, expected in ((0, 2), (3, 1), (-1, 4), (-5, 3)):
            self.values(source, [expected], [value])

    def test_loop_result_matches_formula_on_many_inputs(self):
        result = self.compile("f(n:int) returns r:int uses i:int { i=0;r=0;while(i<n) { r=r+i;i=i+1; } }")
        for n in range(-2, 30):
            expected = [n * (n - 1) // 2 if n > 0 else 0]
            for version in (result.before, result.after):
                with self.subTest(n=n):
                    self.assertEqual(execute(version, "f", [n]), expected)

    def test_nested_loops_and_local_reassignment(self):
        self.values("f() returns r:int uses i:int,j:int { r=0;i=0;while(i<3) { j=0;while(j<2) { r=r+1;j=j+1; } i=i+1; } }", [6])

    def test_forward_call_and_nested_arguments(self):
        self.values("f(x:int) returns r:int { r=add(twice(x),twice(x+1)); } "
                    "add(x:int,y:int) returns r:int { r=x+y; } twice(x:int) returns r:int { r=x*2; }", [14], [3])

    def test_factorial_recursion(self):
        self.values("f(n:int) returns r:int { if(n<=1) r=1; else r=n*f(n-1); }", [720], [6])

    def test_mutually_recursive_calls(self):
        source = ("f(n:int) returns r:int { if(n==0) r=0; else r=g(n-1); } "
                  "g(n:int) returns r:int { if(n==0) r=1; else r=f(n-1); }")
        self.values(source, [0], [8])
        self.values(source, [1], [9])

    def test_tuple_assignment_uses_old_arguments_and_all_results(self):
        source = ("swap(a:int,b:int) returns x:int,y:int { x=b;y=a; } "
                  "f() returns r:int uses x:int,y:int { x=3;y=7;x,y=swap(x,y);r=x*10+y; }")
        self.values(source, [73])

    def test_tuple_can_return_array_and_integer(self):
        source = ("pair(a:int[]) returns n:int,b:int[] { n=length(a);b=a; } "
                  "f(a:int[]) returns r:int,b:int[] uses n,c { n,c=pair(a);c[0]=n;r=c[0];b=c; }")
        self.values(source, [2, [2, 9]], [[4, 9]])

    def test_arrays_copy_update_and_input_nonmutation(self):
        args = [[3, 5, 7]]
        original = deepcopy(args)
        self.values("f(a:int[]) returns old:int,new:int,b:int[] { b=a;b[1]=9;old=a[1];new=b[1]; }", [5, 9, [3, 9, 7]], args)
        self.assertEqual(args, original)

    def test_arrays_are_unchanged_by_callee_updates(self):
        self.values("change(a:int[]) returns b:int[] { b=a;b[0]=99; } "
                    "f(a:int[]) returns r:int,b:int[] { b=change(a);r=a[0]; }", [4, [99, 5]], [[4, 5]])

    def test_short_circuit_skips_trapping_right_hand_side(self):
        for condition in ("false and 1/0>0", "true or 1/0>0", "false -> 1/0>0",
                          "not (true or 1/0>0)", "false and (true -> 1/0>0)"):
            with self.subTest(condition=condition):
                expected = 1 if condition in {"true or 1/0>0", "false -> 1/0>0"} else 2
                self.values("f() returns r:int { if(" + condition + ") r=1;else r=2; }", [expected])

    def test_short_circuit_evaluates_needed_right_hand_side(self):
        for condition in ("true and 1/0>0", "false or 1/0>0", "true -> 1/0>0"):
            self.trap("f() returns r:int { if(" + condition + ") r=1;else r=2; }", "division_by_zero")

    def test_unused_division_error_is_not_eliminated(self):
        self.trap("f() returns r:int uses unused:int { unused=1/0;r=2; }", "division_by_zero")
        self.trap("f(x:int) returns r:int uses unused:int { unused=0/x;r=2; }", "division_by_zero", [0])

    def test_unused_array_access_still_checks_bounds(self):
        self.trap("f(a:int[]) returns r:int uses unused:int { unused=a[2];r=0; }", "array_bounds", [[1]])

    def test_negative_index_is_an_error_instead_of_python_indexing(self):
        self.trap("f(a:int[]) returns r:int { r=a[-1]; }", "array_bounds", [[1, 2]])
        self.trap("f(a:int[]) returns r:int[] { r=a;r[-1]=3; }", "array_bounds", [[1, 2]])

    def test_unused_call_still_has_its_runtime_error(self):
        self.trap("bad() returns r:int { r=1/0; } f() returns r:int uses unused:int { unused=bad();r=1; }", "division_by_zero")

    def test_unused_update_still_checks_bounds(self):
        self.trap("f(a:int[]) returns r:int uses b:int[] { b=a;b[4]=3;r=0; }", "array_bounds", [[]])

    def test_uninitialized_read_keeps_code_and_source_position(self):
        result = self.compile("f() returns r:int uses x:int {\n  r=x;\n}")
        for version in (result.before, result.after):
            with self.assertRaises(IRRuntimeError) as caught:
                execute(version, "f")
            self.assertEqual(caught.exception.code, "uninitialized")
            self.assertEqual(caught.exception.pos, {"line": 2, "col": 5})

    def test_unused_uninitialized_read_is_not_eliminated(self):
        self.trap("f() returns r:int uses x:int,y:int { y=x+1;r=1; }", "uninitialized")

    def test_only_one_branch_initializes_variable(self):
        source = "f(n:int) returns r:int uses x:int,y:int { if(n>0) x=1; y=x;r=0; }"
        self.values(source, [0], [1])
        self.trap(source, "uninitialized", [0])

    def test_contracts_formulas_and_spec_statements_are_retained(self):
        source = ("p(x:int)=>forall(i:int | i>0 -> x>=0); "
                  "f(x:int) requires p(x) returns r:int ensures false { assert false;assume false;r=x; }")
        result = self.values(source, [4], [4])
        for module in (result.before, result.after):
            self.assertEqual(len(module["formulas"]), 1)
            function = module["functions"][0]
            self.assertIn("requires", function["contracts"])
            specifications = [instruction for block in function["blocks"] for instruction in block["instructions"]
                              if instruction["op"] == "spec"]
            self.assertEqual([instruction["kind"] for instruction in specifications], ["assert", "assume"])

    def test_ast_api_does_not_mutate_annotated_input(self):
        ast = check("f() returns r:int { r=1+2; }").ast
        original = deepcopy(ast)
        result = compile_ast(ast)
        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(ast, original)
        self.assertEqual(execute(result.after, "f"), [3])

    def test_source_cse_reuses_repeated_expression_through_leaf_copies(self):
        source = "f(a:int,b:int) returns r:int uses x:int,y:int {x=a+b;y=a+b;r=x+y;}"
        for cse, expected_count in ((True, 2), (False, 3)):
            with self.subTest(cse=cse):
                result = self.values(source, [10], [2, 3], constants=False, simplify=False,
                                     dce=False, cse=cse)
                operations = [instruction for function in result.after["functions"]
                              for block in function["blocks"] for instruction in block["instructions"]
                              if instruction["op"] == "binary" and instruction["operator"] == "+"]
                self.assertEqual(len(operations), expected_count)
                if not cse:
                    self.assertEqual(result.before, result.after)

    def test_ast_api_exposes_cse_option_and_no_opt_bypasses_it(self):
        ast = check("f(a:int,b:int) returns r:int uses x:int,y:int {x=a+b;y=a+b;r=x+y;}").ast
        original = deepcopy(ast)
        for cse in (False, True):
            for optimize in (False, True):
                with self.subTest(cse=cse, optimize=optimize):
                    result = compile_ast(ast, optimize=optimize, constants=False,
                                         simplify=False, dce=False, cse=cse)
                    self.assertTrue(result.ok, result.to_dict())
                    self.assertEqual(execute(result.after, "f", [2, 3]), [10])
                    operations = [instruction for function in result.after["functions"]
                                  for block in function["blocks"] for instruction in block["instructions"]
                                  if instruction["op"] == "binary"]
                    self.assertEqual(len(operations), 2 if cse and optimize else 3)
                    if not optimize:
                        self.assertEqual(result.before, result.after)
        self.assertEqual(ast, original)

    def test_cse_preserves_runtime_error_and_source_position(self):
        for source, args, code in (
            ("f(a:int,b:int) returns r:int uses x:int,y:int {\n"
             "x=a+b;y=a+b;\nr=(x+y)/0;}", [2, 3], "division_by_zero"),
            ("f(a:int) returns r:int uses x:int,y:int,z:int {\n"
             "y=x+a;z=x+a;r=y+z;}", [2], "uninitialized"),
        ):
            observations = []
            for cse in (False, True):
                result = self.compile(source, constants=False, simplify=False, dce=False, cse=cse)
                for version in (result.before, result.after):
                    with self.subTest(code=code, cse=cse, version=version is result.after):
                        with self.assertRaises(IRRuntimeError) as caught:
                            execute(version, "f", args)
                        self.assertEqual(caught.exception.code, code)
                        observations.append((caught.exception.code, caught.exception.pos))
            self.assertTrue(all(observation == observations[0] for observation in observations))

    def test_previous_phase_errors_prevent_lowering(self):
        for source, phase in (("f() returns r:int { r=missing; }", "semantic"),
                              ("f() returns r:int { r=; }", "syntax"),
                              ("f() returns r:int { r=😀; }", "lexical")):
            result = compile_source(source)
            self.assertFalse(result.ok)
            self.assertIsNone(result.before)
            self.assertIsNone(result.after)
            self.assertIn(phase, [error.phase for error in result.diagnostics])

    def test_optimization_flags_are_independent_and_no_opt_keeps_ir(self):
        source = "f(x:int) returns r:int uses dead:int,a:int,b:int { dead=x+0;a=x+2;b=x+2;r=a+b; }"
        plain = self.compile(source, optimize=False)
        self.assertEqual(plain.before, plain.after)
        for flag in ("constants", "simplify", "cse", "dce"):
            self.values(source, [22], [9], **{flag: False})

    def test_metrics_and_diagnostics_are_serializable(self):
        import json
        result = self.compile("f() returns r:int uses x:int { x=1+2;r=4+5; }")
        self.assertGreater(result.metrics["instructions_removed"], 0)
        self.assertGreater(result.metrics["temporaries_removed"], 0)
        self.assertEqual(json.loads(json.dumps(result.to_dict())), result.to_dict())

    def test_execution_limits_and_argument_validation(self):
        self.trap("f() returns r:int { while(true) r=1; }", "step_limit", max_steps=25)
        self.trap("f() returns r:int { r=f(); }", "recursion_limit", max_depth=8)
        result = self.compile("f(x:int,a:int[]) returns r:int { r=x+length(a); }")
        for args, code in (([], "argument_count"), ([True, []], "argument_type"),
                           ([1, [True]], "argument_type"), ([1, 3], "argument_type")):
            with self.subTest(args=args):
                with self.assertRaises(IRRuntimeError) as caught:
                    execute(result.after, "f", args)
                self.assertEqual(caught.exception.code, code)
        with self.assertRaises(IRRuntimeError) as caught:
            execute(result.after, "missing", [])
        self.assertEqual(caught.exception.code, "unknown_function")

    def test_formula_only_module_has_no_runtime_function(self):
        result = self.compile("p(x:int)=>x>0;")
        self.assertEqual(result.metrics["before"]["colors"], 0)
        with self.assertRaises(IRRuntimeError) as caught:
            execute(result.after, "p", [1])
        self.assertEqual(caught.exception.code, "unknown_function")

    def test_operations_are_exact_at_signed_boundaries(self):
        self.assertEqual(i32((1 << 32) + 5), 5)
        self.assertEqual(evaluate_unary("-", -2147483648), -2147483648)
        self.assertEqual(evaluate_binary("/", -2147483648, -1), -2147483648)
        self.assertEqual(evaluate_binary("/", -2147483647, 3), -715827882)
        with self.assertRaises(ZeroDivisionError):
            evaluate_binary("/", 1, 0)


if __name__ == "__main__":
    unittest.main()
