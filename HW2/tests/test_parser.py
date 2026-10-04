"""Независимые проверки синтаксиса и AST: python -m unittest discover -s HW2/tests."""

import json
from pathlib import Path
import subprocess
import sys
import unittest

from HW2.funnyparse import parse


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def shape(value):
    """Координаты не учитываются только в проверках структуры; эталоны проверяют их полностью."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items() if key != "pos"}
    if isinstance(value, list):
        return [shape(item) for item in value]
    return value


def integer(value):
    return {"kind": "Int", "value": value}


def name(value):
    return {"kind": "Name", "name": value}


def binary(op, left, right):
    return {"kind": "Binary", "op": op, "left": left, "right": right}


class ParserTests(unittest.TestCase):
    def valid(self, source):
        result = parse(source)
        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(result.diagnostics, [])
        return result.ast

    def invalid(self, source, phase="syntax"):
        result = parse(source)
        self.assertFalse(result.ok, source)
        self.assertTrue(result.diagnostics, source)
        self.assertTrue(any(d.phase == phase for d in result.diagnostics), result.to_dict())
        for diagnostic in result.diagnostics:
            self.assertGreaterEqual(diagnostic.line, 1)
            self.assertGreaterEqual(diagnostic.col, 1)
            self.assertTrue(diagnostic.message.strip())
        return result

    def expression(self, expression):
        module = self.valid(f"main() returns r:int {{ r = {expression}; }}")
        return shape(module["declarations"][0]["body"]["statements"][0]["value"])

    def predicate(self, predicate):
        module = self.valid(f"main() returns r:int {{ assert {predicate}; }}")
        return shape(module["declarations"][0]["body"]["statements"][0]["predicate"])

    def test_reference_cases_and_handwritten_ast_snapshot(self):
        cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
        for case in cases:
            with self.subTest(case=case["name"]):
                result = parse(case["input"])
                self.assertEqual(result.ok, case["valid"], result.to_dict())
                if "ast" in case:
                    self.assertEqual(result.ast, case["ast"])
                if "diagnostics" in case:
                    expected = case["diagnostics"]
                    self.assertEqual(len(result.diagnostics), len(expected), result.to_dict())
                    for actual, wanted in zip(result.diagnostics, expected):
                        for key in ("phase", "line", "col"):
                            if key in wanted:
                                self.assertEqual(getattr(actual, key), wanted[key])
                        if "message" in wanted:
                            self.assertIn(wanted["message"], actual.message)

    def test_arithmetic_precedence(self):
        self.assertEqual(self.expression("1 + 2 * 3 - 4"),
                         binary("-", binary("+", integer(1),
                                              binary("*", integer(2), integer(3))), integer(4)))

    def test_arithmetic_is_left_associative(self):
        self.assertEqual(self.expression("8 - 3 - 1"),
                         binary("-", binary("-", integer(8), integer(3)), integer(1)))
        self.assertEqual(self.expression("24 / 4 / 2"),
                         binary("/", binary("/", integer(24), integer(4)), integer(2)))

    def test_unary_minus_and_parentheses(self):
        self.assertEqual(self.expression("-(1 + 2) * --3"),
                         binary("*", {"kind": "Unary", "op": "-", "operand":
                                      binary("+", integer(1), integer(2))},
                                {"kind": "Unary", "op": "-", "operand":
                                 {"kind": "Unary", "op": "-", "operand": integer(3)}}))

    def test_logical_precedence_and_right_associative_implication(self):
        boolean = lambda value: {"kind": "Bool", "value": value}
        self.assertEqual(self.predicate("not x == 1 and y < 2 or z >= 3 -> true -> false"),
                         binary("->", binary("or",
                                binary("and", {"kind": "Unary", "op": "not", "operand":
                                               binary("==", name("x"), integer(1))},
                                       binary("<", name("y"), integer(2))),
                                binary(">=", name("z"), integer(3))),
                                binary("->", boolean(True), boolean(False))))

    def test_unicode_and_ascii_arrows_have_same_ast_and_original_positions(self):
        predicates = []
        for operator in ("->", "→"):
            with self.subTest(operator=operator):
                source = f"f() returns r:int {{ assert true {operator} false {operator} true; }}"
                predicate = self.valid(source)["declarations"][0]["body"]["statements"][0]["predicate"]
                predicates.append(shape(predicate))
                self.assertEqual(predicate["op"], "->")
                self.assertEqual(predicate["pos"], {"line": 1, "col": 33})
                self.assertEqual(predicate["right"]["op"], "->")
                self.assertEqual(predicate["right"]["pos"],
                                 {"line": 1, "col": 42 if operator == "->" else 41})
                self.assertEqual(predicate["right"]["left"]["pos"],
                                 {"line": 1, "col": 36 if operator == "->" else 35})
                self.assertEqual(predicate["right"]["right"]["pos"],
                                 {"line": 1, "col": 45 if operator == "->" else 43})
        self.assertEqual(predicates[0], predicates[1])
        self.assertEqual(predicates[1], binary("->", {"kind": "Bool", "value": True},
                                             binary("->", {"kind": "Bool", "value": False},
                                                    {"kind": "Bool", "value": True})))
        adjacent = self.valid("f() returns r:int {\n  // →→ Русский 😀\n  assert true→false→true;\n}")
        predicate = adjacent["declarations"][0]["body"]["statements"][0]["predicate"]
        self.assertEqual(shape(predicate), predicates[1])
        self.assertEqual(predicate["pos"], {"line": 3, "col": 14})
        self.assertEqual(predicate["right"]["pos"], {"line": 3, "col": 20})
        self.assertEqual(predicate["right"]["left"]["pos"], {"line": 3, "col": 15})
        self.assertEqual(predicate["right"]["right"]["pos"], {"line": 3, "col": 21})

    def test_course_sorted_formula_with_unicode_arrow(self):
        # Этот пример в репозитории сохраняет исходную программу Funny из step12.
        source = (ROOT / "HW2" / "examples" / "good_formulas.funny").read_text(encoding="utf-8")
        self.assertIn("→", source)
        declarations = self.valid(source)["declarations"]
        self.assertEqual([declaration["name"] for declaration in declarations],
                         ["is_sorted", "check_sorted"])
        predicate = declarations[0]["predicate"]["predicate"]
        self.assertEqual(predicate["op"], "->")
        self.assertEqual(predicate["pos"], {"line": 3, "col": 45})
        self.assertEqual(predicate["right"]["pos"], {"line": 3, "col": 52})

    def test_all_comparisons(self):
        for operator in ("==", "!=", "<", "<=", ">", ">="):
            with self.subTest(operator=operator):
                self.assertEqual(self.predicate(f"1 {operator} 2"),
                                 binary(operator, integer(1), integer(2)))

    def test_parenthesized_arithmetic_and_parenthesized_predicates(self):
        self.assertEqual(self.predicate("((x + 1) * 2 >= 4) and (true or false)"),
                         binary("and", binary(">=", binary("*", binary("+", name("x"),
                                                                                  integer(1)), integer(2)), integer(4)),
                                binary("or", {"kind": "Bool", "value": True},
                                       {"kind": "Bool", "value": False})))

    def test_calls_and_indexing(self):
        self.assertEqual(self.expression("inc(add(1, 2)) + a[length(a) - 1]"),
                         binary("+", {"kind": "Call", "name": "inc", "args":
                                      [{"kind": "Call", "name": "add", "args": [integer(1), integer(2)]}]},
                                {"kind": "Index", "base": name("a"), "index":
                                 binary("-", {"kind": "Call", "name": "length", "args": [name("a")]}, integer(1))}))

    def test_function_contracts_and_locals(self):
        source = "increment(x:int) requires x >= 0 returns y:int ensures y > x uses t, a:int[] { t = x + 1; y = t; }"
        function = shape(self.valid(source)["declarations"][0])
        self.assertEqual(function["name"], "increment")
        self.assertEqual(function["params"], [{"kind": "VariableDecl", "name": "x", "type": "int"}])
        self.assertEqual(function["returns"], [{"kind": "VariableDecl", "name": "y", "type": "int"}])
        self.assertEqual(function["requires"], binary(">=", name("x"), integer(0)))
        self.assertEqual(function["ensures"], binary(">", name("y"), name("x")))
        self.assertEqual(function["locals"], [
            {"kind": "VariableDecl", "name": "t", "type": None},
            {"kind": "VariableDecl", "name": "a", "type": "int[]"}])

    def test_missing_contracts_and_invariant_use_language_defaults(self):
        function = self.valid("main() returns r:int { while (true) {} }")["declarations"][0]
        self.assertEqual(shape(function["requires"]), {"kind": "Bool", "value": True})
        self.assertEqual(shape(function["ensures"]), {"kind": "Bool", "value": False})
        loop = function["body"]["statements"][0]
        self.assertEqual(shape(loop["invariant"]), {"kind": "Bool", "value": True})

    def test_formula_declarations_and_quantifiers(self):
        source = "allMatch(a:int[]) => forall (i:int | exists (j:int | a[i] == j)); main(a:int[]) requires allMatch(a) returns r:int { r = 0; }"
        declarations = shape(self.valid(source))["declarations"]
        self.assertEqual(declarations[0], {
            "kind": "Formula", "name": "allMatch", "params":
            [{"kind": "VariableDecl", "name": "a", "type": "int[]"}],
            "predicate": {"kind": "Quantifier", "quantifier": "forall", "variable":
                          {"kind": "VariableDecl", "name": "i", "type": "int"}, "predicate":
                          {"kind": "Quantifier", "quantifier": "exists", "variable":
                           {"kind": "VariableDecl", "name": "j", "type": "int"}, "predicate":
                           binary("==", {"kind": "Index", "base": name("a"), "index": name("i")}, name("j"))}}})
        self.assertEqual(declarations[1]["requires"],
                         {"kind": "Call", "name": "allMatch", "args": [name("a")]})

    def test_formula_semicolon_is_optional(self):
        self.valid("positive(x:int) => x > 0 main() returns r:int { r = 1; }")

    def test_function_keyword_and_requires_after_returns_compatibility(self):
        function = self.valid("function f(x:int) returns r:int requires x >= 0 ensures r > x { r = x + 1; }")["declarations"][0]
        self.assertEqual(function["name"], "f")
        self.assertEqual(function["pos"], {"line": 1, "col": 1})
        self.assertEqual(function["params"][0]["pos"], {"line": 1, "col": 12})

    def test_nested_if_attaches_else_to_nearest_if(self):
        outer = self.valid("f() returns r:int { if (true) if (false) r = 1; else r = 2; }")["declarations"][0]["body"]["statements"][0]
        self.assertIsNone(outer["else"])
        self.assertEqual(outer["then"]["kind"], "If")
        self.assertEqual(outer["then"]["else"]["value"]["value"], 2)

    def test_while_invariant_and_nested_block(self):
        loop = self.valid("sum(n:int) returns r:int uses i { i = 0; r = 0; while (i < n) invariant 0 <= i and r >= 0 { { r = r + i; } i = i + 1; } }")["declarations"][0]["body"]["statements"][2]
        self.assertEqual(loop["kind"], "While")
        self.assertEqual(loop["invariant"]["op"], "and")
        self.assertEqual(loop["body"]["statements"][0]["kind"], "Block")

    def test_assert_and_assume(self):
        statements = self.valid("divide(x:int,y:int) returns r:int { assume y != 0; r = x / y; assert r * y == x; }")["declarations"][0]["body"]["statements"]
        self.assertEqual([statement["kind"] for statement in statements], ["Assume", "Assign", "Assert"])
        self.assertEqual(statements[0]["predicate"]["op"], "!=")
        self.assertEqual(statements[2]["predicate"]["op"], "==")

    def test_single_statement_function_body(self):
        function = self.valid("constant() returns r:int r = 7;")["declarations"][0]
        self.assertEqual(function["body"]["kind"], "Assign")

    def test_tuple_assignment(self):
        statement = self.valid("main() returns r:int uses x,y { x,y = split(9); r = x-y; }")["declarations"][0]["body"]["statements"][0]
        self.assertEqual(shape(statement), {"kind": "Assign", "targets": [name("x"), name("y")],
                                           "value": {"kind": "Call", "name": "split", "args": [integer(9)]}})

    def test_array_update_is_desugared(self):
        statement = self.valid("update(a:int[]) returns b:int[] { b[0] = 42; }")["declarations"][0]["body"]["statements"][0]
        self.assertEqual(shape(statement), {"kind": "Assign", "targets": [name("b")], "value":
                                           {"kind": "ArrayUpdate", "base": name("b"), "index": integer(0), "value": integer(42)}})

    def test_nested_array_update_preserves_outer_array(self):
        statement = self.valid("update(a:int[]) returns b:int[] { b[0][1] = 7; }")["declarations"][0]["body"]["statements"][0]
        self.assertEqual(shape(statement), {"kind": "Assign", "targets": [name("b")], "value":
                                           {"kind": "ArrayUpdate", "base": name("b"), "index": integer(0), "value":
                                            {"kind": "ArrayUpdate", "base": {"kind": "Index", "base": name("b"), "index": integer(0)},
                                             "index": integer(1), "value": integer(7)}}})

    def test_positions_after_lf_crlf_and_cr(self):
        for newline in ("\n", "\r\n", "\r"):
            with self.subTest(newline=repr(newline)):
                source = newline.join(["main() returns r:int {", "  r = 1;", "}"])
                statement = self.valid(source)["declarations"][0]["body"]["statements"][0]
                self.assertEqual(statement["pos"], {"line": 2, "col": 3})
                self.assertEqual(statement["value"]["pos"], {"line": 2, "col": 7})
                result = self.invalid(newline.join(["main() returns r:int {", "  r = ;", "}"]))
                self.assertEqual((result.diagnostics[0].line, result.diagnostics[0].col), (2, 7))

    def test_unicode_comments_preserve_positions(self):
        source = "// Русский комментарий → 😀\nmain() returns r:int {\n  r = 1; // значение\n}\n"
        statement = self.valid(source)["declarations"][0]["body"]["statements"][0]
        self.assertEqual(statement["pos"], {"line": 3, "col": 3})
        self.assertEqual(statement["value"]["pos"], {"line": 3, "col": 7})

    def test_unicode_code_and_unknown_symbol_are_lexical_errors(self):
        for symbol in ("я", "😀", "@"):
            with self.subTest(symbol=symbol):
                result = self.invalid(f"main() returns r:int {{ r = 1 {symbol} 2; }}", phase="lexical")
                lexical = next(d for d in result.diagnostics if d.phase == "lexical")
                self.assertEqual((lexical.line, lexical.col), (1, 30))

    def test_leading_zero_is_a_lexical_error(self):
        result = self.invalid("main() returns r:int { r = 007; }", phase="lexical")
        lexical = next(d for d in result.diagnostics if d.phase == "lexical")
        self.assertEqual((lexical.line, lexical.col), (1, 28))

    def test_empty_and_comment_only_inputs_are_invalid(self):
        for source in ("", " \t\n", "// только комментарий\n"):
            with self.subTest(source=source):
                self.invalid(source)

    def test_eof_spelling_is_an_identifier_and_not_end_of_input(self):
        function = self.valid("EOF() returns EOF:int { EOF = 1; }")["declarations"][0]
        self.assertEqual(function["name"], "EOF")
        self.assertEqual(function["returns"][0]["name"], "EOF")
        self.assertEqual(function["body"]["statements"][0]["targets"][0]["name"], "EOF")
        self.valid("f(EOF:int) returns r:int { r = EOF; }")
        self.invalid("f() returns r:int { r=1; } EOF junk")
        self.invalid("f() returns r:int { r=1; } EOF")

    def test_length_call_is_arithmetic_and_not_a_formula(self):
        self.valid("f(a:int[]) returns r:int { r = length(a); assert length(a) > 0; }")
        self.invalid("f(a:int[]) returns r:int { assert length(a); }")

    def test_expression_and_predicate_contexts_are_distinct(self):
        for source in (
            "f() returns r:int { r = true; }",
            "f() returns r:int { r = 1 < 2; }",
            "f() returns r:int { r = not false; }",
            "f() returns r:int { if (1) {} }",
            "f() returns r:int { while (r) {} }",
            "f() returns r:int { assert r; }",
            "f() returns r:int { assume 1 + 2; }",
            "f() returns r:int { assert true + 1 == 2; }",
            "f() returns r:int { assert 1 < 2 < 3; }",
        ):
            with self.subTest(source=source):
                self.invalid(source)

    def test_tuple_requires_call_and_plain_variable_targets(self):
        for source in ("f() returns r:int { x,y = 1; }", "f() returns r:int { x,y = foo() + 1; }",
                       "f() returns r:int { x[0],y = foo(); }"):
            with self.subTest(source=source):
                self.invalid(source)

    def test_quantifiers_are_predicates(self):
        self.valid("f() returns r:int { assert forall (i:int | i == i); }")
        self.invalid("f() returns r:int { r = forall (i:int | true); }")
        self.invalid("f() returns r:int { if (forall (i:int | true)) {} }")
        self.invalid("f() returns r:int { if (someFormula(1)) {} }")

    def test_semantic_checks_are_deferred(self):
        # Поиск имён, изменяемость, число аргументов и вывод типов относятся к HW3.
        for source in (
            "f() returns r:int { r = unknown + 1; }",
            "f() returns r:int { r = missing(1, 2); }",
            "f(x:int) returns r:int { x = 1; r = x; }",
            "f(a:int[]) returns r:int { r = a[a]; }",
            "f(x:int) returns r:int { r = length(x); }",
            "f(x:int,x:int) returns r:int { r = x; }",
            "f() returns r:int { assert missingPredicate(1); }",
        ):
            with self.subTest(source=source):
                self.valid(source)

    def test_panic_recovery_preserves_following_statement_and_function(self):
        result = self.invalid("bad() returns r:int { r = ; r = 2; }\ngood() returns r:int { r = 3; }")
        functions = result.ast["declarations"]
        self.assertEqual([function["name"] for function in functions], ["bad", "good"])
        self.assertTrue(any(statement.get("value", {}).get("value") == 2
                            for statement in functions[0]["body"]["statements"]))
        self.assertEqual(functions[1]["body"]["statements"][0]["value"]["value"], 3)
        self.assertEqual((result.diagnostics[0].line, result.diagnostics[0].col), (1, 27))

    def test_missing_closing_block_preserves_following_function(self):
        result = self.invalid("bad() returns r:int { r = 1;\ngood() returns r:int { r = 2; }")
        self.assertIn("good", [function.get("name") for function in result.ast["declarations"]])

    def test_negative_inputs_terminate_in_separate_process(self):
        # Тайм-аут выявляет зацикливание при восстановлении после ошибки, не давая unittest зависнуть.
        inputs = ["", "}", "; ; ;", "f(", "f() returns r:int {", "f() returns r:int { r = (((1; }",
                  "f() returns r:int { if (true { r = 1; } }", "f() returns r:int { r = 1 ** 2; }",
                  "f() returns r:int { r = 1; else r = 2; }", "f() returns r:int { assert exists (i:int true); }"]
        script = "import json,sys; from HW2.funnyparse import parse; results=[parse(x).ok for x in json.loads(sys.stdin.read())]; print(json.dumps(results))"
        completed = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                                   input=json.dumps(inputs), text=True, encoding="utf-8",
                                   capture_output=True, timeout=15, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), [False] * len(inputs))

    def test_serialization_is_json_compatible_and_retains_diagnostics(self):
        result = self.invalid("f() returns r:int { r = ; }")
        serialized = result.to_dict()
        self.assertEqual(json.loads(json.dumps(serialized)), serialized)
        self.assertEqual(serialized["ast"], result.ast)
        self.assertEqual(serialized["diagnostics"][0]["phase"], result.diagnostics[0].phase)
        self.assertEqual(serialized["diagnostics"][0]["line"], result.diagnostics[0].line)
        self.assertEqual(serialized["diagnostics"][0]["col"], result.diagnostics[0].col)
        self.assertEqual(serialized["diagnostics"][0]["message"], result.diagnostics[0].message)

    def test_examples_have_expected_status(self):
        examples = sorted((ROOT / "HW2" / "examples").glob("*.funny"))
        self.assertTrue(examples)
        for example in examples:
            with self.subTest(example=example.name):
                result = parse(example.read_text(encoding="utf-8"))
                self.assertEqual(result.ok, example.name.startswith("good_"), result.to_dict())


if __name__ == "__main__":
    unittest.main()
