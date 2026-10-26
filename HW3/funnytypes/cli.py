"""Командная строка: python -m HW3.funnytypes <команда>

    check   проверить файл или --text, вывести типизированный AST и ошибки
    test    проверить программы, диагностику и типы из tests/cases.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

from HW2.funnyparse.cli import first_difference, short_json, tree_lines

from . import check


DEFAULT_CASES = Path(__file__).resolve().parents[1] / "tests" / "cases.json"
_FIELD = r"[A-Za-z_][A-Za-z_0-9]*"
_PATH = re.compile(_FIELD + r"(?:\." + _FIELD + r"|\[\d+\])*")
_PART = re.compile(_FIELD + r"|\[(\d+)\]")
_DIAGNOSTIC_FIELDS = {"phase", "line", "col", "message", "code"}
_TYPES = {"int", "int[]", "bool", "error"}


def cmd_check(args):
    if args.text is not None:
        source = args.text
    else:
        with open(args.file, encoding="utf-8-sig", newline="") as stream:
            source = stream.read()
    result = check(source, args.table)
    if args.format == "json":
        output = json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n"
    else:
        output = "\n".join(tree_lines(result.ast)) + "\n"
        for diagnostic in result.to_dict()["diagnostics"]:
            code = " [%s]" % diagnostic["code"] if diagnostic.get("code") else ""
            output += "%d:%d: %s%s: %s\n" % (
                diagnostic["line"], diagnostic["col"], diagnostic["phase"], code,
                diagnostic["message"])
    if args.out is None:
        print(output, end="")
    else:
        with open(args.out, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(output)
    return 0 if result.ok else 1


def path_parts(path):
    """Разбить declarations[0].name на имена полей и индексы списков."""
    if not isinstance(path, str) or not _PATH.fullmatch(path):
        raise ValueError("Некорректный путь type_checks: %r" % path)
    parts = [int(match.group(1)) if match.group(1) is not None else match.group()
             for match in _PART.finditer(path)]
    if parts[0] == "ast":
        parts = parts[1:]
    if not parts:
        raise ValueError("type_checks: путь должен указывать поле AST")
    return parts


def value_at_path(ast, path):
    value = ast
    for part in path_parts(path):
        # Число в пути означает индекс списка, строка — имя поля словаря.
        if isinstance(part, int):
            if not isinstance(value, list):
                raise TypeError("ожидался список")
        elif not isinstance(value, dict):
            raise TypeError("ожидался объект")
        value = value[part]
    return value


def load_cases(path):
    with open(path, encoding="utf-8-sig") as stream:
        document = json.load(stream)
    if not isinstance(document, dict) or not isinstance(document.get("cases"), list):
        raise ValueError("Набор тестов должен содержать список cases")
    cases = document["cases"]
    for index, case in enumerate(cases, 1):
        prefix = "cases[%d]" % (index - 1)
        if not isinstance(case, dict):
            raise ValueError(prefix + ": ожидался объект")
        if not isinstance(case.get("name"), str) or not isinstance(case.get("input"), str):
            raise ValueError(prefix + ": name и input должны быть строками")
        if not isinstance(case.get("valid"), bool):
            raise ValueError(prefix + ": valid должен быть true или false")
        if "diagnostics" in case:
            if not isinstance(case["diagnostics"], list):
                raise ValueError(prefix + ": diagnostics должен быть списком")
            for diagnostic in case["diagnostics"]:
                if not isinstance(diagnostic, dict) or not diagnostic.keys() <= _DIAGNOSTIC_FIELDS:
                    raise ValueError(prefix + ": неверные поля diagnostics")
                for key, value in diagnostic.items():
                    if key in {"line", "col"}:
                        if type(value) is not int or value < 1:
                            raise ValueError(prefix + ": line и col должны быть положительными целыми")
                    elif not isinstance(value, str):
                        raise ValueError(prefix + ": phase, code и message должны быть строками")
        if "type_checks" in case:
            if not isinstance(case["type_checks"], list):
                raise ValueError(prefix + ": type_checks должен быть списком")
            for type_check in case["type_checks"]:
                if not isinstance(type_check, dict) or set(type_check) != {"path", "type"}:
                    raise ValueError(prefix + ": type_checks требует поля path и type")
                path_parts(type_check["path"])
                expected = type_check["type"]
                types = expected if isinstance(expected, list) else [expected]
                if not all(isinstance(item, str) and item in _TYPES for item in types):
                    raise ValueError(prefix + ": неизвестный ожидаемый тип")
    return cases


def diagnostics_difference(expected, actual):
    """Сравнить список по порядку; эталон может задавать часть полей ошибки."""
    if len(expected) != len(actual):
        return "diagnostics.length", len(expected), len(actual)
    for index, (wanted, found) in enumerate(zip(expected, actual)):
        for key, value in wanted.items():
            received = found.get(key)
            matches = (isinstance(received, str) and value in received
                       if key == "message" else received == value)
            if not matches:
                return "diagnostics[%d].%s" % (index, key), value, received
    return None


def types_difference(expected, ast):
    for type_check in expected:
        path, wanted = type_check["path"], type_check["type"]
        try:
            found = value_at_path(ast, path)
        except (KeyError, IndexError, TypeError):
            found = "<нет такого поля>"
        if found != wanted:
            return "ast." + path.removeprefix("ast."), wanted, found
    return None


def difference_text(difference):
    path, wanted, found = difference
    return "%s: ожидалось %s, получено %s" % (path, short_json(wanted), short_json(found))


def print_case(index, total, case, result, errors, diagnostics_match, types_match):
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
    for diagnostic in result.to_dict()["diagnostics"]:
        code = " [%s]" % diagnostic["code"] if diagnostic.get("code") else ""
        print("    %s%s %d:%d: %s" % (
            diagnostic["phase"], code, diagnostic["line"], diagnostic["col"], diagnostic["message"]))
    if "ast" in case:
        print("  AST: " + ("совпадает с эталоном" if case["ast"] == result.ast else "не совпадает с эталоном"))
    if "diagnostics" in case:
        print("  Ожидаемая диагностика: " + json.dumps(case["diagnostics"], ensure_ascii=False))
        print("  Диагностика: " + ("совпадает с эталоном" if diagnostics_match else "не совпадает с эталоном"))
    if "type_checks" in case:
        print("  Типы: " + ("совпадают с эталоном" if types_match else "не совпадают с эталоном"))


def cmd_test(args):
    cases = load_cases(args.cases)
    failed = 0
    for index, case in enumerate(cases, 1):
        result = check(case["input"], args.table)
        actual = result.to_dict()
        errors = []
        if result.ok != case["valid"]:
            errors.append(difference_text(("valid", case["valid"], result.ok)))
        if "ast" in case and result.ast != case["ast"]:
            errors.append(difference_text(first_difference(case["ast"], result.ast)))
        diagnostics_match = types_match = None
        if "diagnostics" in case:
            difference = diagnostics_difference(case["diagnostics"], actual["diagnostics"])
            diagnostics_match = difference is None
            if difference:
                errors.append(difference_text(difference))
        if "type_checks" in case:
            difference = types_difference(case["type_checks"], result.ast)
            types_match = difference is None
            if difference:
                errors.append(difference_text(difference))
        failed += bool(errors)
        if args.verbose:
            print_case(index, len(cases), case, result, errors, diagnostics_match, types_match)
        elif errors:
            print("FAIL  " + case["name"])
        for error in errors:
            print("      " + error)
        if args.verbose:
            print()
    print("%d cases: %d passed, %d failed" % (len(cases), len(cases) - failed, failed))
    return 1 if failed else 0


def main():
    # Терминал Windows может использовать cp1251; вывод всегда остаётся UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="funnytypes", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("check", help="проверить файл или --text; вывести типизированный AST и ошибки")
    command.add_argument("file", nargs="?")
    command.add_argument("--text")
    command.add_argument("--format", choices=("json", "tree"), default="json")
    command.add_argument("--out", help="записать результат в файл UTF-8")
    command.add_argument("--table", help="таблица ДКА HW1 в JSON; штатный путь определяется по модулю")
    command.set_defaults(func=cmd_check)
    command = sub.add_parser("test", help="проверить программы, диагностику и выведенные типы")
    command.add_argument("--cases", default=str(DEFAULT_CASES))
    command.add_argument("--table")
    command.add_argument("-v", "--verbose", action="store_true",
                         help="показать каждый тест: программу, ожидаемый результат и ошибки")
    command.set_defaults(func=cmd_test)
    args = parser.parse_args()
    if args.command == "check" and args.file is None and args.text is None:
        parser.error("check: укажите файл или --text")
    if args.command == "check" and args.file is not None and args.text is not None:
        parser.error("check: выберите файл либо --text")
    try:
        return args.func(args)
    except RecursionError:
        print("error: AST слишком глубок для выбранного формата вывода", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 2
