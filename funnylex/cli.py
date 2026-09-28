"""Командная строка:  python -m funnylex <команда>

    build   tokens.spec -> generated/   (НКА -> ДКА -> минимальный ДКА, таблицы)
    test    прогнать tests/cases.json через таблицу и напечатать PASS/FAIL
    lex     разбить текст (файл или --text) на токены
"""

import argparse
import json
import sys
from pathlib import Path

from . import export
from .dfa import subset_construction
from .minimize import minimize
from .nfa import build_nfa
from .scanner import Table, classify, tokenize
from .spec import load_spec


def build_automata(rules):
    """Весь конвейер: правила -> НКА -> ДКА -> минимальный ДКА."""
    nfa = build_nfa([rule.tree for rule in rules])
    dfa, _ = subset_construction(nfa)
    return nfa, dfa, minimize(dfa)


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def cmd_build(args):
    rules = load_spec(args.spec)
    nfa, dfa, mini = build_automata(rules)
    if dfa.accept[dfa.start] is not None:
        raise ValueError("правило %s принимает пустую строку" % rules[dfa.accept[dfa.start]].name)
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    write(out / "dfa.json", export.to_json(export.to_dict(dfa, rules, args.spec)))
    write(out / "dfa.min.json", export.to_json(export.to_dict(mini, rules, args.spec)))
    write(out / "dfa.min.csv", export.to_csv(mini, rules))
    write(out / "dfa.min.dot", export.to_dot(mini, rules))
    print("rules:          %d" % len(rules))
    print("NFA states:     %d" % nfa.n_states)
    print("DFA states:     %d (with trap)" % dfa.n_states)
    print("min DFA states: %d (with trap; trap = state %d)" % (mini.n_states, mini.trap()))
    for i, rule in enumerate(rules):         # правило, до которого не дойти из-за верхних
        if i not in mini.accept:
            print("WARNING: rule %s can never match (shadowed by rules above it)" % rule.name)
    print("written to %s/" % out)


def cmd_test(args):
    table = Table.load(args.table)
    with open(args.cases, encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    failed = 0
    for case in cases:
        if case["mode"] == "match":          # вся строка должна быть одним токеном
            actual = classify(table, case["input"])
        else:                                # строка режется на токены
            tokens = tokenize(table, case["input"], case.get("keep_skipped", False))
            actual = [[t.kind, t.lexeme] for t in tokens]
        ok = actual == case["expect"]
        failed += not ok
        if not ok or args.verbose:
            print("%s  %-5s %s" % ("PASS" if ok else "FAIL", case["mode"], case["name"]))
        if not ok:
            print("      input:    %s" % json.dumps(case["input"]))
            print("      expected: %s" % json.dumps(case["expect"]))
            print("      actual:   %s" % json.dumps(actual))
    print("%d cases: %d passed, %d failed" % (len(cases), len(cases) - failed, failed))
    return 1 if failed else 0


def cmd_lex(args):
    table = Table.load(args.table)
    if args.text is not None:
        text = args.text
    else:
        # newline="" - не превращать \r\n в \n: лексер должен видеть текст как есть
        with open(args.file, encoding="utf-8", newline="") as f:
            text = f.read()
    tokens = tokenize(table, text, args.keep_skipped)
    for t in tokens:
        mark = "" if t.category == "token" else "  <%s>" % t.category
        print("%d:%d\t%-10s %s%s" % (t.line, t.col, t.kind, json.dumps(t.lexeme), mark))
    errors = sum(t.category == "error" for t in tokens)
    if errors:
        print("lexical errors: %d" % errors, file=sys.stderr)
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(prog="funnylex", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="build automata and tables from tokens.spec")
    p.add_argument("--spec", default="tokens.spec")
    p.add_argument("--out", default="generated")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("test", help="run tests/cases.json through the table")
    p.add_argument("--table", default="generated/dfa.min.json")
    p.add_argument("--cases", default="tests/cases.json")
    p.add_argument("-v", "--verbose", action="store_true", help="print PASS lines too")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("lex", help="tokenize a file or --text")
    p.add_argument("file", nargs="?")
    p.add_argument("--text")
    p.add_argument("--table", default="generated/dfa.min.json")
    p.add_argument("--keep-skipped", action="store_true", help="also print WS and COMMENT")
    p.set_defaults(func=cmd_lex)

    args = parser.parse_args()
    if args.command == "lex" and args.file is None and args.text is None:
        parser.error("lex: give a file or --text")
    try:
        return args.func(args) or 0
    except (ValueError, OSError) as error:   # плохой tokens.spec, нет файла, битый JSON
        print("error: %s" % error, file=sys.stderr)
        return 2
