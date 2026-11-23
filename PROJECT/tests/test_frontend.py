from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from HW2.funnyparse import parse
from HW3.funnytypes import check, check_ast
from HW4.funnyir import execute
from PROJECT.funnyjvm import compile_source


ROOT = Path(__file__).resolve().parents[2]


class ProjectFrontendTests(unittest.TestCase):
    def valid(self, source):
        result = compile_source(source)
        self.assertTrue(result.ok, result.diagnostics)
        return result

    def invalid(self, source, code):
        result = compile_source(source)
        self.assertFalse(result.ok)
        self.assertIn(code, [getattr(item, "code", None) for item in result.diagnostics])
        return result

    def test_scalar_array_and_explicit_locals_share_function_scope(self):
        result = self.valid(
            "main(input:int[]) returns r:int uses n:int {"
            "copy=input; n=length(copy); if(n>0){tmp=copy[0];}else{tmp=0;} r=tmp;}"
        )
        function = result.after["functions"][0]
        self.assertEqual({item["name"]: item["type"] for item in function["locals"]},
                         {"n": "int", "copy": "int[]", "tmp": "int"})
        for module in (result.before, result.after):
            self.assertEqual(execute(module, arguments=[[7]]), [7])
            self.assertEqual(execute(module, arguments=[[]]), [0])

    def test_tuple_assignment_introduces_all_result_variables(self):
        result = self.valid(
            "pair(x:int) returns a:int,b:int {a=x;b=x+1;}"
            "main() returns r:int {a,b=pair(3);r=a+b;}"
        )
        self.assertEqual(execute(result.after), [7])

    def test_reads_do_not_declare_names_or_infer_types(self):
        self.invalid("main() returns r:int {r=missing;}", "unknown_variable")
        self.invalid("main() returns r:int {r=x;x=1;}", "unresolved_type")
        self.invalid("main() returns r:int {x=x;r=0;}", "unresolved_type")

    def test_first_valid_assignment_fixes_type_and_rollback_preserves_inference(self):
        self.invalid("main(a:int[]) returns r:int {x=1;x=a;r=0;}", "type_mismatch")
        checked = check("main(a:int[]) returns r:int {x=missing;x=a;r=0;}", implicit_locals=True)
        self.assertEqual(checked.ast["declarations"][0]["locals"][0]["inferred_type"], "int[]")
        self.assertEqual([item.code for item in checked.diagnostics], ["unknown_variable"])

    def test_parameters_and_contract_scopes_remain_checked(self):
        self.invalid("main(n:int) returns r:int {n=n-1;r=n;}", "readonly_assignment")
        self.invalid("main(a:int[]) returns r:int {a[0]=1;r=0;}", "readonly_assignment")
        self.invalid("main() returns r:int ensures x>0 {x=1;r=x;}", "unknown_variable")
        self.valid(
            "main(n:int) returns r:int {i=0;r=0;"
            "while(i<n) invariant i>=0 {r=r+i;i=i+1;}}"
        )

    def test_assignment_declarations_do_not_mutate_input_ast(self):
        ast = parse("main() returns r:int {x=1;r=x;}").ast
        snapshot = deepcopy(ast)
        checked = check_ast(ast, implicit_locals=True)
        self.assertTrue(checked.ok, checked.diagnostics)
        self.assertEqual(ast, snapshot)
        self.assertEqual(checked.ast["declarations"][0]["locals"][0]["pos"], {"line": 1, "col": 23})

    def test_hw3_requires_explicit_declarations_by_default(self):
        checked = check("main() returns r:int {x=1;r=x;}")
        self.assertFalse(checked.ok)
        self.assertIn("unknown_variable", [item.code for item in checked.diagnostics])

    def test_cli_runs_an_original_course_file_with_implicit_tuple_locals(self):
        source = ROOT / "PROJECT/tests/course/original/step03/good_multi_return.funny"
        process = subprocess.run(
            [sys.executable, "-B", "-m", "PROJECT.funnyjvm", "run", str(source)],
            cwd=ROOT, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), [1])
