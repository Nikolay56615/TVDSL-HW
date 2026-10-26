"""Командная строка HW4: построение IR, исполнение и эталонные тесты."""

import argparse
import json
import sys
from pathlib import Path

from . import IRRuntimeError, compile_source, execute
from .ir import cfg_dot, format_ir, interference_dot


DEFAULT_CASES = Path(__file__).resolve().parents[1] / "tests" / "cases.json"
_DIAGNOSTIC_FIELDS = {"phase", "code", "line", "col", "message"}
_LIMIT_CODES = {"step_limit", "recursion_limit"}


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def typed_equal(left, right):
    """В Python True == 1; при сравнении результатов Funny это разные значения."""
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(typed_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(typed_equal(left[k], right[k]) for k in left)
    return left == right


def write_output(output, path=None):
    if path is None:
        print(output, end="")
    else:
        Path(path).write_text(output, encoding="utf-8", newline="\n")


def diagnostic_text(item):
    code = " [%s]" % item["code"] if item.get("code") else ""
    return "%s%s %s:%s: %s" % (
        item.get("phase", "error"), code, item.get("line", "?"),
        item.get("col", "?"), item.get("message", ""))


def compile_input(args):
    source = args.text if args.text is not None else Path(args.file).read_text(encoding="utf-8-sig")
    return compile_source(source, optimize=not args.no_opt, constants=not args.no_constants,
                          simplify=not args.no_simplify, cse=not args.no_cse,
                          dce=not args.no_dce, table=args.table)


def export_graphs(args, result):
    if not (args.cfg_dot or args.interference_dot):
        return
    module = result.after
    functions = module["functions"]
    selected = next((item for item in functions if item["name"] == args.function), None)
    if args.function is None and functions:
        selected = functions[0]
    if selected is None:
        raise ValueError("Для DOT не найдена функция %r" % args.function)
    analysis = result.analysis_after[selected["name"]]
    if args.cfg_dot:
        write_output(cfg_dot(selected, analysis["cfg"]), args.cfg_dot)
    if args.interference_dot:
        write_output(interference_dot(selected, analysis["interference"], analysis["colors"]),
                     args.interference_dot)


def cmd_build(args):
    result = compile_input(args)
    document = result.to_dict()
    if args.format == "json":
        output = json_text(document)
    elif result.ok and args.format == "text":
        output = ("IR ДО оптимизаций\n" + format_ir(result.before).rstrip() + "\n\n"
                  "IR ПОСЛЕ оптимизаций\n" + format_ir(result.after).rstrip() + "\n\n"
                  "Метрики\n" + json_text(result.metrics))
    elif result.ok:
        output = "Ошибок нет.\n"
    else:
        output = "\n".join(diagnostic_text(item) for item in document["diagnostics"]) + "\n"
    if result.ok:
        export_graphs(args, result)
    write_output(output, args.out)
    return 0 if result.ok else 1


def validate_arguments(module, function, arguments):
    declaration = next((item for item in module["functions"] if item["name"] == function), None)
    if declaration is None:
        raise ValueError("Неизвестная функция: " + function)
    if not isinstance(arguments, list):
        raise ValueError("--args должен содержать JSON-массив аргументов")
    if len(arguments) != len(declaration["params"]):
        raise ValueError("Функция %s ожидает %d аргументов, получено %d" % (
            function, len(declaration["params"]), len(arguments)))
    for parameter, value in zip(declaration["params"], arguments):
        kind = parameter["type"]
        valid = (type(value) is int if kind == "int" else
                 isinstance(value, list) and all(type(element) is int for element in value)
                 if kind == "int[]" else type(value) is bool)
        if not valid:
            raise ValueError("Аргумент %s должен иметь тип %s" % (parameter["name"], kind))


def outcome(module, function, arguments, max_steps, max_depth):
    try:
        return {"result": execute(module, function, arguments,
                                  max_steps=max_steps, max_depth=max_depth)}
    except IRRuntimeError as error:
        return {"error": error.to_dict()}


def compare_outcomes(before, after):
    """Сравнение одного запуска, включая одинаковые наблюдаемые ошибки."""
    if any(item.get("error", {}).get("code") in _LIMIT_CODES for item in (before, after)):
        return None, "inconclusive"
    if "result" in before and "result" in after:
        equal = typed_equal(before["result"], after["result"])
    elif "error" in before and "error" in after:
        equal = before["error"]["code"] == after["error"]["code"]
    else:
        equal = False
    return equal, "equal" if equal else "different"


def cmd_run(args):
    arguments = json.loads(args.args)
    result = compile_input(args)
    if not result.ok:
        write_output(json_text({"diagnostics": result.to_dict()["diagnostics"]}), args.out)
        return 1
    validate_arguments(result.before, args.function, arguments)
    export_graphs(args, result)
    if args.compare:
        before = outcome(result.before, args.function, arguments, args.max_steps, args.max_depth)
        after = outcome(result.after, args.function, arguments, args.max_steps, args.max_depth)
        equal, comparison = compare_outcomes(before, after)
        write_output(json_text({"before": before, "after": after,
                                "equivalent": equal, "comparison": comparison}), args.out)
        return 0 if equal is True else 1
    actual = outcome(result.before if args.before else result.after, args.function, arguments,
                     args.max_steps, args.max_depth)
    write_output(json_text(actual["result"] if "result" in actual else actual), args.out)
    return 0 if "result" in actual else 1


def load_cases(path):
    document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict) or not isinstance(document.get("cases"), list):
        raise ValueError("Набор тестов должен содержать список cases")
    for index, case in enumerate(document["cases"]):
        prefix = "cases[%d]: " % index
        if not isinstance(case, dict):
            raise ValueError(prefix + "ожидался объект")
        if not isinstance(case.get("name"), str) or not isinstance(case.get("input"), str):
            raise ValueError(prefix + "name и input должны быть строками")
        if "valid" in case and type(case["valid"]) is not bool:
            raise ValueError(prefix + "valid должен быть true или false")
        if case.get("valid", True):
            if ("result" in case) == ("error" in case):
                raise ValueError(prefix + "укажите ровно одно из result или error")
            if "result" in case and not isinstance(case["result"], list):
                raise ValueError(prefix + "result должен быть списком результатов")
            if "error" in case and not isinstance(case["error"], str):
                raise ValueError(prefix + "error должен быть кодом ошибки")
            if not isinstance(case.get("function", "main"), str):
                raise ValueError(prefix + "function должен быть строкой")
            if not isinstance(case.get("args", []), list):
                raise ValueError(prefix + "args должен быть списком")
            for limit in ("max_steps", "max_depth"):
                if limit in case and (type(case[limit]) is not int or case[limit] < 1):
                    raise ValueError(prefix + limit + " должен быть положительным целым")
        elif not isinstance(case.get("diagnostics"), list) or not case["diagnostics"]:
            raise ValueError(prefix + "некорректная программа требует непустой diagnostics")
        for diagnostic in case.get("diagnostics", []):
            if not isinstance(diagnostic, dict) or not diagnostic.keys() <= _DIAGNOSTIC_FIELDS:
                raise ValueError(prefix + "неверные поля diagnostics")
            for key, value in diagnostic.items():
                if key in {"line", "col"}:
                    if type(value) is not int or value < 1:
                        raise ValueError(prefix + "line и col должны быть положительными целыми")
                elif not isinstance(value, str):
                    raise ValueError(prefix + "phase, code, message должны быть строками")
    return document["cases"]


def diagnostics_match(expected, actual):
    if len(expected) != len(actual):
        return False
    return all(all((isinstance(found.get(key), str) and value in found[key]
                    if key == "message" else typed_equal(value, found.get(key)))
                   for key, value in wanted.items())
               for wanted, found in zip(expected, actual))


def compact(value):
    return json.dumps(value, ensure_ascii=False)


def run_case(case, table=None):
    result = compile_source(case["input"], table=table)
    actual = {"valid": result.ok, "diagnostics": result.to_dict()["diagnostics"]}
    errors = []
    if result.ok != case.get("valid", True):
        errors.append("корректность программы не совпала с эталоном")
    if not result.ok:
        if "diagnostics" in case and not diagnostics_match(case["diagnostics"], actual["diagnostics"]):
            errors.append("диагностика не совпала с эталоном")
        return actual, errors
    if case.get("valid", True) is False:
        return actual, errors
    function, arguments = case.get("function", "main"), case.get("args", [])
    validate_arguments(result.before, function, arguments)
    limits = case.get("max_steps", 100000), case.get("max_depth", 128)
    actual["before"] = outcome(result.before, function, arguments, *limits)
    actual["after"] = outcome(result.after, function, arguments, *limits)
    equal, comparison = compare_outcomes(actual["before"], actual["after"])
    actual["comparison"] = comparison
    for stage in ("before", "after"):
        found = actual[stage]
        matches = ("result" in found and typed_equal(case["result"], found["result"])
                   if "result" in case else found.get("error", {}).get("code") == case["error"])
        if not matches:
            errors.append(stage + ": результат не совпал с эталоном")
    if equal is False:
        errors.append("исполнения до и после оптимизации различаются")
    # Ожидаемый лимит проверяет защиту интерпретатора, но не эквивалентность.
    if equal is None and case.get("error") not in _LIMIT_CODES:
        errors.append("сравнение не завершено из-за ограничения исполнения")
    return actual, errors


def print_case(index, total, case, actual, errors):
    print("[%02d/%02d] %s  %s" % (index, total, "FAIL" if errors else "PASS", case["name"]))
    print("  Программа:")
    for line in case["input"].splitlines() or ["<пустой ввод>"]:
        print("    " + line)
    if case.get("valid", True):
        print("  Функция: %s; аргументы: %s" % (case.get("function", "main"), compact(case.get("args", []))))
        print("  Ожидалось: " + ("результат " + compact(case["result"]) if "result" in case
                                  else "ошибка " + case["error"]))
        for stage, title in (("before", "ДО"), ("after", "ПОСЛЕ")):
            if stage in actual:
                print("  Получено " + title + ": " + compact(actual[stage]))
        if "comparison" in actual:
            message = {"equal": "наблюдения совпали", "different": "наблюдения различаются",
                       "inconclusive": "лимит исполнения: эквивалентность не установлена"}
            print("  Сравнение ДО/ПОСЛЕ: " + message[actual["comparison"]])
    else:
        print("  Ожидалось: некорректная программа; диагностика " + compact(case["diagnostics"]))
    print("  Получено: " + ("корректная программа" if actual["valid"] else "некорректная программа"))
    for diagnostic in actual["diagnostics"]:
        print("    " + diagnostic_text(diagnostic))


def cmd_test(args):
    cases = load_cases(args.cases)
    failed = 0
    for index, case in enumerate(cases, 1):
        actual, errors = run_case(case, args.table)
        failed += bool(errors)
        if args.verbose:
            print_case(index, len(cases), case, actual, errors)
        elif errors:
            print("FAIL  " + case["name"])
        for error in errors:
            print("      " + error)
        if args.verbose:
            print()
    print("%d cases: %d passed, %d failed" % (len(cases), len(cases) - failed, failed))
    return 1 if failed else 0


def positive_integer(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("ожидалось положительное целое") from error
    if number < 1:
        raise argparse.ArgumentTypeError("ожидалось положительное целое")
    return number


def add_input_options(command):
    command.add_argument("file", nargs="?")
    command.add_argument("--text", help="исходный текст вместо файла")
    command.add_argument("--out", help="сохранить вывод в UTF-8")
    command.add_argument("--table", help="JSON-таблица ДКА HW1")
    command.add_argument("--no-opt", action="store_true", help="отключить все оптимизации")
    command.add_argument("--no-constants", action="store_true", help="отключить константы")
    command.add_argument("--no-simplify", action="store_true", help="отключить алгебраические упрощения")
    command.add_argument("--no-cse", action="store_true", help="отключить повторное использование выражений")
    command.add_argument("--no-dce", action="store_true", help="отключить удаление мёртвых вычислений")
    command.add_argument("--cfg-dot", help="сохранить CFG после оптимизации в DOT")
    command.add_argument("--interference-dot", help="сохранить граф конфликтов после оптимизации в DOT")


def main(argv=None):
    # Перенаправление вывода в Windows также должно давать читаемый UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="funnyir", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="построить IR до и после оптимизаций")
    add_input_options(build)
    build.add_argument("--format", choices=("text", "json"),
                       help="по умолчанию: сообщения об ошибках или «Ошибок нет»; "
                            "text — IR до/после и метрики; json — полный результат")
    build.add_argument("--function", help="функция для DOT; по умолчанию первая")
    build.set_defaults(func=cmd_build)
    run = commands.add_parser("run", help="исполнить IR или сравнить два исполнения")
    add_input_options(run)
    run.add_argument("--function", default="main")
    run.add_argument("--args", default="[]", help="аргументы в JSON, например [1,[2,3]]")
    run.add_argument("--compare", action="store_true", help="сравнить исполнение до и после")
    run.add_argument("--before", action="store_true", help="исполнить IR до оптимизаций")
    run.add_argument("--max-steps", type=positive_integer, default=100000)
    run.add_argument("--max-depth", type=positive_integer, default=128)
    run.set_defaults(func=cmd_run)
    test = commands.add_parser("test", help="проверить эталонные результаты и диагностику")
    test.add_argument("--cases", default=str(DEFAULT_CASES))
    test.add_argument("--table")
    test.add_argument("-v", "--verbose", action="store_true", help="показать программы, ожидания и результаты")
    test.set_defaults(func=cmd_test)
    args = parser.parse_args(argv)
    if args.command in {"build", "run"}:
        if (args.file is None) == (args.text is None):
            parser.error(args.command + ": укажите ровно одно: файл либо --text")
    if args.command == "run" and args.before and args.compare:
        parser.error("run: выберите --before либо --compare")
    try:
        return args.func(args)
    except RecursionError:
        print("error: слишком глубокое дерево или JSON", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 2
