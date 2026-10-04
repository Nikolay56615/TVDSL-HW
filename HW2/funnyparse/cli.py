"""Командная строка: python -m HW2.funnyparse <команда>

    parse   разобрать файл или --text, вывести дерево и ошибки
    test    проверить программы и ожидаемые результаты из tests/cases.json
"""

import argparse
import json
import sys
from pathlib import Path

from . import parse


DEFAULT_CASES = Path(__file__).resolve().parents[1] / "tests" / "cases.json"


def tree_lines(value, indent=""):
    """AST-словарь -> строки с отступами. Узлы печатаются как 'Assign @2:5'."""
    if isinstance(value, dict):
        if "kind" in value:
            pos = value["pos"]
            yield "%s%s @%d:%d" % (indent, value["kind"], pos["line"], pos["col"])
            indent += "  "
        for key, child in value.items():
            if key in ("kind", "pos"):
                continue
            if isinstance(child, (dict, list)):
                yield indent + key + ":"
                yield from tree_lines(child, indent + "  ")
            else:
                yield indent + key + ": " + json.dumps(child, ensure_ascii=False)
    elif isinstance(value, list):
        if not value:
            yield indent + "[]"
        for child in value:
            yield from tree_lines(child, indent)


def cmd_parse(args):
    if args.text is not None:
        source = args.text
    else:
        with open(args.file, encoding="utf-8-sig", newline="") as stream:
            source = stream.read()
    result = parse(source, args.table)
    if args.format == "json":
        output = json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n"
    else:
        output = "\n".join(tree_lines(result.ast)) + "\n"
        for diagnostic in result.diagnostics:
            output += "%d:%d: %s: %s\n" % (diagnostic.line, diagnostic.col,
                                            diagnostic.phase, diagnostic.message)
    if args.out is None:
        print(output, end="")
    else:
        with open(args.out, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(output)
    return 0 if result.ok else 1


def first_difference(expected, actual, path="ast"):
    """Первое отличающееся поле двух деревьев, например ast.declarations[0].body.kind."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        if expected.keys() != actual.keys():
            return path + ".keys", list(expected), list(actual)
        for key in expected:
            if expected[key] != actual[key]:
                return first_difference(expected[key], actual[key], path + "." + key)
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return path + ".length", len(expected), len(actual)
        for index, (wanted, found) in enumerate(zip(expected, actual)):
            if wanted != found:
                return first_difference(wanted, found, "%s[%d]" % (path, index))
    return path, expected, actual


def short_json(value):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 120 else text[:117] + "..."


def print_test_case(index, total, case, result, errors, diagnostics_match):
    print("[%02d/%02d] %s  %s" % (index, total, "FAIL" if errors else "PASS", case["name"]))
    source = case["input"]
    if not source:
        print("  Программа: <пустой ввод>")
    elif not source.strip():
        print("  Программа: " + repr(source))
    else:
        print("  Программа:")
        for line in source.splitlines():
            print("    " + line)
    print("  Ожидалось: " + ("корректная программа" if case["valid"] else "некорректная программа"))
    print("  Получено: " + ("корректная программа, ошибок нет" if result.ok else "некорректная программа"))
    for diagnostic in result.diagnostics:
        print("    %s %d:%d: %s" % (diagnostic.phase, diagnostic.line, diagnostic.col,
                                    diagnostic.message))
    if "ast" in case:
        if case["ast"] == result.ast:
            print("  AST: совпадает с эталоном")
        else:
            path, wanted, found = first_difference(case["ast"], result.ast)
            print("  AST: не совпадает с эталоном")
            print("    %s: ожидалось %s, получено %s" % (path, short_json(wanted), short_json(found)))
    if "diagnostics" in case:
        print("  Диагностика: " + ("совпадает с эталоном" if diagnostics_match else "не совпадает с эталоном"))


def cmd_test(args):
    with open(args.cases, encoding="utf-8") as stream:
        cases = json.load(stream)["cases"]
    failed = 0
    for index, case in enumerate(cases, 1):
        result = parse(case["input"], args.table)
        actual = result.to_dict()
        errors = []
        if result.ok != case["valid"]:
            errors.append("valid: ожидалось %r, получено %r" % (case["valid"], result.ok))
        if "ast" in case and result.ast != case["ast"]:
            errors.append("AST не совпадает с эталонным деревом")
        diagnostics_match = None
        if "diagnostics" in case:
            expected = case["diagnostics"]
            diagnostics = actual["diagnostics"]
            # В эталоне можно указать только нужные поля; message ищем как подстроку.
            diagnostics_match = len(expected) == len(diagnostics) and not any(
                any((value not in found[key] if key == "message" else found[key] != value)
                    for key, value in wanted.items())
                for wanted, found in zip(expected, diagnostics)
            )
            if not diagnostics_match:
                errors.append("diagnostics: ожидалось %r, получено %r" % (expected, diagnostics))
        failed += bool(errors)
        if args.verbose:
            print_test_case(index, len(cases), case, result, errors, diagnostics_match)
        elif errors:
            print("%s  %s" % ("FAIL" if errors else "PASS", case["name"]))
        for error in errors:
            print("      " + error)
        if args.verbose:
            print()
    print("%d cases: %d passed, %d failed" % (len(cases), len(cases) - failed, failed))
    return 1 if failed else 0


def main():
    # В Windows cp1251 не умеет печатать → и emoji из сообщений об ошибках.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="funnyparse", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("parse", help="разобрать файл или --text; вывести AST и диагностику")
    command.add_argument("file", nargs="?")
    command.add_argument("--text")
    command.add_argument("--format", choices=("json", "tree"), default="json")
    command.add_argument("--out", help="записать результат в файл UTF-8")
    command.add_argument("--table", help="таблица ДКА HW1 в JSON; штатный путь определяется по модулю")
    command.set_defaults(func=cmd_parse)
    command = sub.add_parser("test", help="проверить положительные и отрицательные эталоны AST")
    command.add_argument("--cases", default=str(DEFAULT_CASES))
    command.add_argument("--table")
    command.add_argument("-v", "--verbose", action="store_true",
                         help="показать каждый тест: программу, ожидаемый результат и ошибки")
    command.set_defaults(func=cmd_test)
    args = parser.parse_args()
    if args.command == "parse" and args.file is None and args.text is None:
        parser.error("parse: укажите файл или --text")
    if args.command == "parse" and args.file is not None and args.text is not None:
        parser.error("parse: выберите файл либо --text")
    try:
        return args.func(args)
    except RecursionError:
        print("error: AST слишком глубок для выбранного формата вывода", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 2
