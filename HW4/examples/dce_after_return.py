"""Пример удаления недостижимого кода после return.

В исходном Funny команды return нет, поэтому пример сразу задаёт IR.
Блок AfterReturn содержит безопасное сложение, но входящих переходов нет.
"""

import argparse

from HW4.funnyir import execute
from HW4.funnyir.ir import format_ir
from HW4.funnyir.optimize import optimize_module


def example_module():
    return {
        "version": 1,
        "formulas": [],
        "functions": [{
            "name": "main",
            "params": [],
            "returns": [{"name": "r", "type": "int"}],
            "locals": [{"name": "unused", "type": "int"}],
            "types": {"v:r": "int", "v:unused": "int"},
            "entry": "B0",
            "contracts": {"requires": None, "ensures": None, "invariants": []},
            "blocks": [
                {"label": "B0", "instructions": [
                    {"op": "copy", "dest": "v:r", "args": [{"const": 7}]},
                    {"op": "return", "args": [{"var": "v:r"}]},
                ]},
                {"label": "AfterReturn", "instructions": [
                    {"op": "binary", "dest": "v:unused", "operator": "+",
                     "args": [{"const": 10}, {"const": 20}]},
                    {"op": "return", "args": [{"var": "v:unused"}]},
                ]},
            ],
        }],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-dce", action="store_true", help="оставить недостижимый блок")
    args = parser.parse_args()
    before = example_module()
    after = optimize_module(before, constants=False, simplify=False, cse=False, dce=not args.no_dce)
    before_result, after_result = execute(before), execute(after)
    print("IR ДО DCE")
    print(format_ir(before))
    print("IR БЕЗ DCE" if args.no_dce else "IR ПОСЛЕ DCE")
    print(format_ir(after))
    print("Результат до:", before_result)
    print("Результат после:", after_result)
    return 0 if before_result == after_result else 1


if __name__ == "__main__":
    raise SystemExit(main())
