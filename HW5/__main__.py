"""Проверка темпоральных свойств модели в Spin."""

import argparse
import os
from pathlib import Path
import sys

from .checker import CASES, PROPERTIES, ROOT, verify


def positive(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("Значение должно быть положительным")
    return result


def print_result(result, expected=None, *, show_trace=False):
    name = result["property"]
    outcome = "верно" if result["holds"] else "нарушено"
    if expected is None:
        print(f"{name}: {outcome} — {PROPERTIES[name]}")
    else:
        status = "PASS" if result["holds"] == expected else "FAIL"
        expectation = "верно" if expected else "нарушено"
        print(f"{status} {name}: {outcome}, ожидалось {expectation} — {PROPERTIES[name]}")
    if result["trace"]:
        print("  Контрпример сохранён в " + result["trace"])
        if show_trace:
            for line in Path(result["trace"]).read_text(encoding="utf-8").splitlines():
                if line.lstrip().startswith("STATE ") or "START OF CYCLE" in line:
                    print("  " + line.strip())


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="HW5", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="проверить модель и сохранить логи")
    test = commands.add_parser("test", help="сверить исправную и ошибочные модели с эталоном")
    local_spin = ROOT / ".tools" / "spin.exe"
    default_spin = str(local_spin) if local_spin.is_file() else "spin"
    for command in (check, test):
        command.add_argument("--spin", default=os.environ.get("SPIN", default_spin))
        command.add_argument("--cc", default=os.environ.get("CC", "gcc"))
        command.add_argument("--out", type=Path, default=ROOT / "results")
        command.add_argument("--no-por", action="store_true", help="отключить уменьшение числа перестановок переходов")
        command.add_argument("--depth", type=positive, default=10000)
        command.add_argument("--timeout", type=positive, default=60, help="лимит каждого внешнего процесса в секундах")
    check.add_argument("--variant", choices=tuple(CASES), default="correct")
    check.add_argument("--retries", type=int, choices=range(6), default=2)
    check.add_argument("--property", action="append", choices=tuple(PROPERTIES))
    check.add_argument("--trace", action="store_true", help="показать состояния контрпримера")
    args = parser.parse_args(argv)
    settings = dict(spin=args.spin, cc=args.cc, por=not args.no_por,
                    depth=args.depth, timeout=args.timeout)
    try:
        if args.command == "check":
            report, directory = verify(args.variant, args.retries,
                                       dict.fromkeys(args.property or PROPERTIES), args.out, **settings)
            for result in report["results"]:
                print_result(result, show_trace=args.trace)
            print("Логи и параметры проверки в " + str(directory))
            return 0 if all(result["holds"] for result in report["results"]) else 1

        passed = total = 0
        scenarios = [(variant, 2) for variant in CASES] + [("correct", 0), ("correct", 3)]
        for variant, retries in scenarios:
            print(f"Модель {variant}, максимум повторов {retries}", flush=True)
            report, directory = verify(variant, retries, PROPERTIES, args.out, **settings)
            for result in report["results"]:
                expected = result["property"] not in CASES[variant]["fails"]
                print_result(result, expected)
                passed += result["holds"] == expected
                total += 1
            print("Логи в " + str(directory), flush=True)
        print(f"Проверки: {passed}/{total}")
        return 0 if passed == total else 1
    except (ValueError, OSError) as error:
        print("Ошибка запуска: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
