"""Команды parse (AST и ошибки) и test (проверка эталонов)."""

import argparse
import json
import sys
from pathlib import Path

from . import parse


DEFAULT_CASES = Path(__file__).resolve().parents[1] / "tests" / "cases.json"


def tree_lines(value, indent=""):
    """Человекочитаемое дерево; все поля AST видны, включая позиции."""
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


def cmd_test(args):
    with open(args.cases, encoding="utf-8") as stream:
        cases = json.load(stream)["cases"]
    failed = 0
    for case in cases:
        result = parse(case["input"], args.table)
        actual = result.to_dict()
        errors = []
        if result.ok != case["valid"]:
            errors.append("valid: expected %r, got %r" % (case["valid"], result.ok))
        if "ast" in case and result.ast != case["ast"]:
            errors.append("AST differs from the expected tree")
        if "diagnostics" in case:
            expected = case["diagnostics"]
            diagnostics = actual["diagnostics"]
            if len(expected) != len(diagnostics) or any(
                any((value not in found[key] if key == "message" else found[key] != value)
                    for key, value in wanted.items())
                for wanted, found in zip(expected, diagnostics)
            ):
                errors.append("diagnostics: expected %r, got %r" % (expected, diagnostics))
        failed += bool(errors)
        if errors or args.verbose:
            print("%s  %s" % ("FAIL" if errors else "PASS", case["name"]))
        for error in errors:
            print("      " + error)
    print("%d cases: %d passed, %d failed" % (len(cases), len(cases) - failed, failed))
    return 1 if failed else 0


def main():
    # В Windows перенаправленный stdout может иметь cp1251: JSON и диагностика
    # с неизвестным Unicode-символом всё равно должны выводиться без traceback.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="funnyparse", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("parse", help="parse a file or --text; output AST and diagnostics")
    command.add_argument("file", nargs="?")
    command.add_argument("--text")
    command.add_argument("--format", choices=("json", "tree"), default="json")
    command.add_argument("--out", help="write UTF-8 output to a file")
    command.add_argument("--table", help="DFA JSON from HW1; default resolved from module location")
    command.set_defaults(func=cmd_parse)
    command = sub.add_parser("test", help="run positive/negative AST fixtures")
    command.add_argument("--cases", default=str(DEFAULT_CASES))
    command.add_argument("--table")
    command.add_argument("-v", "--verbose", action="store_true")
    command.set_defaults(func=cmd_test)
    args = parser.parse_args()
    if args.command == "parse" and args.file is None and args.text is None:
        parser.error("parse: give a file or --text")
    if args.command == "parse" and args.file is not None and args.text is not None:
        parser.error("parse: choose a file or --text")
    try:
        return args.func(args)
    except RecursionError:
        print("error: AST слишком глубок для выбранного формата вывода", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 2
