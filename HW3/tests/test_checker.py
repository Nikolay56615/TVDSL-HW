"""Имена, области видимости, вывод типов и ошибки в AST из HW2."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from HW2.funnyparse import parse
from HW3.funnytypes import check, check_ast


HERE = Path(__file__).resolve().parent
EXPRESSIONS = {"Int", "Bool", "Name", "Call", "Binary", "Unary", "Index", "ArrayUpdate", "Quantifier"}


def nodes(value):
    if isinstance(value, dict):
        if "kind" in value:
            yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


class SemanticTests(unittest.TestCase):
    def valid(self, source):
        result = check(source)
        self.assertTrue(result.ok, result.to_dict())
        for node in nodes(result.ast):
            if node["kind"] in EXPRESSIONS:
                self.assertIn("inferred_type", node, node)
                self.assertNotIn(node["inferred_type"], (None, "error"), node)
        return result.ast

    def invalid(self, source, *codes):
        result = check(source)
        self.assertFalse(result.ok, result.to_dict())
        semantic = [diagnostic for diagnostic in result.diagnostics if diagnostic.phase == "semantic"]
        found = [diagnostic.code for diagnostic in semantic]
        for code in codes:
            self.assertIn(code, found, result.to_dict())
        for diagnostic in result.diagnostics:
            self.assertGreaterEqual(diagnostic.line, 1)
            self.assertGreaterEqual(diagnostic.col, 1)
            self.assertTrue(diagnostic.message.strip())
        return result

    def test_fixture_expectations_are_checked_independently(self):
        for case in json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]:
            with self.subTest(case=case["name"]):
                result = check(case["input"])
                self.assertEqual(result.ok, case["valid"], result.to_dict())
                if "diagnostics" in case:
                    diagnostics = [diagnostic.to_dict() for diagnostic in result.diagnostics]
                    self.assertEqual(len(diagnostics), len(case["diagnostics"]), result.to_dict())
                    for expected, actual in zip(case["diagnostics"], diagnostics):
                        for key, value in expected.items():
                            if key == "message":
                                self.assertIn(value, actual[key])
                            else:
                                self.assertEqual(value, actual[key])

    def test_annotations_preserve_original_parser_tree_and_positions(self):
        original = parse("f(x:int) returns r:int uses t { t=x+1; r=t; }").ast
        snapshot = deepcopy(original)
        first = check_ast(original)
        second = check_ast(original)
        self.assertTrue(first.ok, first.to_dict())
        self.assertEqual(original, snapshot)
        self.assertEqual(first.to_dict(), second.to_dict())
        local = first.ast["declarations"][0]["locals"][0]
        self.assertIsNone(local["type"])
        self.assertEqual(local["inferred_type"], "int")
        def remove_annotations(value):
            if isinstance(value, dict):
                return {key: remove_annotations(child) for key, child in value.items()
                        if key not in {"inferred_type", "signature"}}
            if isinstance(value, list):
                return [remove_annotations(child) for child in value]
            return value
        self.assertEqual(remove_annotations(first.ast), snapshot)

    def test_function_signature_is_available_before_body(self):
        ast = self.valid("first(x:int) returns r:int { r=second(x); } second(x:int) returns r:int { r=x+1; }")
        self.assertEqual(ast["declarations"][0]["signature"], {"params": ["int"], "returns": ["int"]})
        call = ast["declarations"][0]["body"]["statements"][0]["value"]
        self.assertEqual(call["inferred_type"], "int")

    def test_recursive_and_mutually_recursive_functions(self):
        self.valid("f(x:int) returns r:int { if(x>0) r=f(x-1); else r=0; }")
        self.valid("f(x:int) returns r:int { r=g(x); } g(x:int) returns r:int { r=f(x); }")

    def test_formula_forward_reference_and_quantifier(self):
        self.valid("f(a:int[]) requires sorted(a) returns r:int ensures r>=0 { r=length(a); } "
                   "sorted(a:int[]) => forall(i:int | i>=0 and i<length(a) -> a[i]>=0);")

    def test_variable_and_callable_names_are_separate(self):
        self.valid("helper(x:int) returns r:int { r=x; } f() returns r:int uses helper:int { helper=2; r=helper(helper); }")

    def test_variables_do_not_leak_between_functions(self):
        result = self.invalid("f() returns r:int uses x:int { x=1; r=x; } g() returns r:int { r=x; }", "unknown_variable")
        self.assertEqual(len(result.diagnostics), 1)

    def test_duplicates_across_all_function_declaration_groups(self):
        for source in ("f(x:int,x:int) returns r:int {}", "f(x:int) returns x:int {}",
                       "f() returns r:int uses r:int {}", "f() returns r:int uses a:int,a:int {}"):
            with self.subTest(source=source):
                self.invalid(source, "duplicate_name")

    def test_function_and_formula_share_global_name_space(self):
        self.invalid("f(x:int) returns r:int { r=x; } f(x:int) => x>0;", "duplicate_name")

    def test_contracts_have_different_visible_names(self):
        self.invalid("f(x:int) requires r>0 returns r:int { r=x; }", "unknown_variable")
        self.invalid("f() returns r:int ensures t>0 uses t:int { t=1; r=t; }", "unknown_variable")
        self.valid("f(x:int) requires x>0 returns r:int ensures r>=x uses t { t=x; r=t; }")

    def test_quantifier_binder_is_scoped_and_cannot_shadow(self):
        self.valid("f() returns r:int { assert forall(i:int | i>0); assert exists(i:int | i<0); r=0; }")
        self.invalid("f() returns r:int { assert forall(i:int | i>0); r=i; }", "unknown_variable")
        self.invalid("f(i:int) returns r:int { assert forall(i:int | i>0); r=0; }", "duplicate_name")
        self.invalid("f() returns r:int { assert forall(i:int | exists(i:int | i>0)); r=0; }", "duplicate_name")

    def test_quantifier_scope_respects_contract_scope(self):
        self.valid("f(x:int) requires forall(r:int | r>=0) returns r:int ensures forall(t:int | t>=0) uses t:int { r=x; }")

    def test_every_arithmetic_operator_requires_integer(self):
        for operator in ("+", "-", "*", "/"):
            with self.subTest(operator=operator):
                self.invalid(f"f(a:int[]) returns r:int {{ r=a {operator} 1; }}", "type_mismatch")
        self.invalid("f(a:int[]) returns r:int { r=-a; }", "type_mismatch")

    def test_every_comparison_requires_integer(self):
        for operator in ("==", "!=", "<", "<=", ">", ">="):
            with self.subTest(operator=operator):
                self.invalid(f"f(a:int[]) returns r:int {{ assert a {operator} a; r=0; }}", "type_mismatch")

    def test_bool_annotations_and_unicode_implication(self):
        ast = self.valid("f(x:int) returns r:int { if(not x==0 and true or false) r=1; else r=2; assert true→false→true; }")
        booleans = [node for node in nodes(ast) if node["kind"] in {"Bool", "Binary", "Unary"}
                    and (node["kind"] == "Bool" or node.get("op") in {"not", "and", "or", "->", "=="})]
        self.assertTrue(booleans)
        self.assertTrue(all(node["inferred_type"] == "bool" for node in booleans))

    def test_length_checks_its_signature(self):
        self.valid("f(a:int[]) returns r:int { r=length(a); }")
        self.invalid("f() returns r:int { r=length(1); }", "type_mismatch")
        self.invalid("f(a:int[]) returns r:int { r=length(a,a); }", "argument_count")

    def test_index_checks_base_and_index_types(self):
        self.invalid("f(x:int) returns r:int { r=x[0]; }", "type_mismatch")
        self.invalid("f(a:int[]) returns r:int { r=a[a]; }", "type_mismatch")
        self.invalid("f(a:int[]) returns r:int { r=a[0][0]; }", "type_mismatch")

    def test_array_update_and_copy_preserve_array_type(self):
        ast = self.valid("f(a:int[]) returns r:int[] uses b { b=a; b[0]=1; r=b; }")
        function = ast["declarations"][0]
        self.assertEqual(function["locals"][0]["inferred_type"], "int[]")
        self.assertEqual(function["body"]["statements"][1]["value"]["inferred_type"], "int[]")

    def test_array_update_requires_integer_value(self):
        self.invalid("f(a:int[]) returns r:int[] uses b:int[] { b=a; b[0]=a; r=b; }", "type_mismatch")

    def test_parameters_are_readonly_even_through_array_update(self):
        self.invalid("f(x:int) returns r:int { x=2; r=x; }", "readonly_assignment")
        self.invalid("f(a:int[]) returns r:int { a[0]=2; r=0; }", "readonly_assignment")
        self.invalid("pair() returns x:int,y:int { x=1;y=2; } f(p:int) returns r:int { p,r=pair(); }", "readonly_assignment")

    def test_arguments_are_checked_even_when_callee_is_unknown(self):
        self.invalid("f() returns r:int { r=missing(unknown); }", "unknown_variable", "unknown_callable")

    def test_argument_count_and_types(self):
        prefix = "take(x:int,a:int[]) returns r:int { r=x; } "
        self.invalid(prefix + "f(a:int[]) returns r:int { r=take(1); }", "argument_count")
        self.invalid(prefix + "f(a:int[]) returns r:int { r=take(a,1); }", "type_mismatch")

    def test_multiple_results_are_only_allowed_in_tuple_assignment(self):
        prefix = "pair(x:int) returns a:int,b:int[] { a=x; } "
        ast = self.valid(prefix + "f() returns r:int uses a,b { a,b=pair(1); r=a; }")
        function = ast["declarations"][1]
        self.assertEqual([local["inferred_type"] for local in function["locals"]], ["int", "int[]"])
        self.assertEqual(function["body"]["statements"][0]["value"]["inferred_type"], ["int", "int[]"])
        self.invalid(prefix + "f() returns r:int { r=pair(1); }", "result_count")
        self.invalid(prefix + "f() returns r:int { r=pair(1)+1; }", "result_count")
        self.invalid(prefix + "f() returns r:int uses a:int,b:int { r,a,b=pair(1); }", "result_count")

    def test_tuple_target_type_mismatch(self):
        self.invalid("pair() returns x:int,y:int { x=1;y=2; } f() returns r:int uses a:int[] { r,a=pair(); }", "type_mismatch")

    def test_formula_and_function_call_contexts(self):
        self.invalid("p(x:int)=>x>0; f() returns r:int { r=p(1); }", "callable_context")
        self.invalid("g() returns r:int { r=1; } f() returns r:int { assert g(); r=0; }", "callable_context")
        self.valid("g() returns r:int { r=1; } f() returns r:int { assert g()>0; r=g(); }")

    def test_local_inference_is_fixed_by_first_valid_assignment(self):
        ast = self.valid("f(a:int[]) returns r:int uses n,b { n=length(a); b=a; r=n; }")
        self.assertEqual([local["inferred_type"] for local in ast["declarations"][0]["locals"]], ["int", "int[]"])
        self.invalid("f(a:int[]) returns r:int uses x { x=1; x=a; r=0; }", "type_mismatch")

    def test_bad_rhs_does_not_determine_local_type(self):
        result = self.invalid("f(a:int[]) returns r:int uses x { x=a+1; x=a; r=0; }", "type_mismatch")
        self.assertEqual(result.ast["declarations"][0]["locals"][0]["inferred_type"], "int[]")
        self.assertNotIn("unresolved_type", [error.code for error in result.diagnostics if error.phase == "semantic"])

    def test_bad_call_does_not_determine_local_type(self):
        result = self.invalid("one(x:int) returns r:int { r=x; } f(a:int[]) returns r:int uses t { t=one(); t=a; r=0; }", "argument_count")
        self.assertEqual(result.ast["declarations"][1]["locals"][0]["inferred_type"], "int[]")

    def test_failed_tuple_assignment_does_not_partially_infer_locals(self):
        result = self.invalid("pair() returns a:int,b:int[] {} f(xs:int[]) returns r:int uses x,y:int { x,y=pair(); x=xs; r=0; }", "type_mismatch")
        self.assertEqual(result.ast["declarations"][1]["locals"][0]["inferred_type"], "int[]")

    def test_unknown_type_read_is_not_retroactively_accepted(self):
        result = self.invalid("f() returns r:int uses x { r=x; x=1; }", "unresolved_type")
        self.assertEqual(result.ast["declarations"][0]["locals"][0]["inferred_type"], "int")

    def test_self_assignment_and_unassigned_local_cannot_infer_type(self):
        self.invalid("f() returns r:int uses x { x=x; r=0; }", "unresolved_type")
        self.invalid("f() returns r:int uses x { r=0; }", "unresolved_type")

    def test_first_array_update_infers_array_from_valid_context(self):
        ast = self.valid("f() returns r:int uses a { a[0]=42; r=length(a); }")
        function = ast["declarations"][0]
        self.assertEqual(function["locals"][0]["inferred_type"], "int[]")
        self.assertEqual(function["body"]["statements"][0]["value"]["base"]["inferred_type"], "int[]")

    def test_invalid_array_update_does_not_lock_in_array_type(self):
        programs = [
            ("f(xs:int[]) returns r:int uses a { a[xs]=1; a=7; r=a; }", "type_mismatch"),
            ("f() returns r:int uses a { a[0][1]=2; a=7; r=a; }", "type_mismatch"),
            ("f() returns r:int uses a { a[0]=a[1]; a=7; r=a; }", "unresolved_type"),
        ]
        for source, code in programs:
            with self.subTest(source=source):
                result = self.invalid(source, code)
                self.assertEqual(result.ast["declarations"][0]["locals"][0]["inferred_type"], "int")

    def test_branch_and_loop_inference_follows_source_order(self):
        self.valid("f() returns r:int uses x { if(true) x=1; else x=2; while(false) { x=x+1; } r=x; }")
        self.invalid("f(a:int[]) returns r:int uses x { if(true) x=1; else x=a; r=0; }", "type_mismatch")

    def test_loop_invariant_can_see_function_variables(self):
        self.valid("f(n:int) returns r:int uses i { i=0; r=0; while(i<n) invariant i>=0 and r>=0 { r=r+1;i=i+1; } }")

    def test_explicit_type_does_not_require_definite_initialization(self):
        self.valid("f() returns r:int uses x:int { r=x; }")

    def test_division_and_bounds_are_not_evaluated_by_type_checker(self):
        self.valid("f(a:int[]) returns r:int { r=a[999]+1/0; }")

    def test_more_than_one_independent_error_is_reported_with_positions(self):
        source = "f(a:int[]) returns r:int {\n  missing = 1;\n  r = length(1);\n  a[0] = 2;\n}"
        result = self.invalid(source, "unknown_variable", "type_mismatch", "readonly_assignment")
        positions = {(error.line, error.col) for error in result.diagnostics}
        self.assertIn((2, 3), positions)
        self.assertIn((3, 14), positions)
        self.assertIn((4, 3), positions)

    def test_lexical_and_syntax_errors_survive_and_later_function_is_checked(self):
        result = check("broken() returns r:int { r=; } good() returns r:int { r=missing; }")
        self.assertFalse(result.ok)
        self.assertIn("syntax", [error.phase for error in result.diagnostics])
        self.assertIn("unknown_variable", [getattr(error, "code", None) for error in result.diagnostics])
        emoji = check("f() returns r:int { r=😀; }")
        self.assertIn("lexical", [error.phase for error in emoji.diagnostics])

    def test_no_cross_request_type_or_name_state(self):
        self.valid("f() returns r:int { r=1; }")
        self.invalid("g() returns r:int { r=f(); }", "unknown_callable")

    def test_crlf_positions_are_original_source_positions(self):
        result = self.invalid("f() returns r:int {\r\n  r = unknown;\r\n}", "unknown_variable")
        diagnostic = next(error for error in result.diagnostics if getattr(error, "code", None) == "unknown_variable")
        self.assertEqual((diagnostic.line, diagnostic.col), (2, 7))


if __name__ == "__main__":
    unittest.main()
