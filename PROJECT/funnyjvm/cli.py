"""Сборка и запуск программы Funny в отдельном процессе JVM."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory

from HW4.funnyir.operations import i32

from . import compile_source
from .backend import RUNTIME_CLASSES, emit_class
from .translation import build_query, solve_query


RUNTIME = Path(__file__).resolve().parents[1] / "runtime"


def _jdk_tool(name):
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / (name + ".exe" if os.name == "nt" else name)
        if candidate.is_file():
            return str(candidate)
    executable = shutil.which(name)
    if not executable:
        raise ValueError(f"Не найден {name}. Установите JDK и добавьте его bin в PATH")
    return executable


def build_runtime(directory):
    sources = [str(RUNTIME / (name + ".java")) for name in RUNTIME_CLASSES]
    process = subprocess.run(
        [_jdk_tool("javac"), "--release", "8", "-encoding", "UTF-8",
         "-d", str(directory), *sources],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    if process.returncode:
        raise ValueError("Ошибка javac: " + process.stderr.strip())


def encode_arguments(arguments, params):
    if not isinstance(arguments, list) or len(arguments) != len(params):
        raise ValueError(f"--args должен быть JSON-массивом из {len(params)} аргументов")
    lines = []
    for value, param in zip(arguments, params):
        if param["type"] == "int" and type(value) is int:
            lines.append(str(i32(value)))
        elif (param["type"] == "int[]" and isinstance(value, list)
              and all(type(item) is int for item in value)):
            lines.append(",".join(str(i32(item)) for item in value))
        else:
            raise ValueError(f"Аргумент {param['name']} должен иметь тип {param['type']}")
    return "".join(line + "\n" for line in lines)


def launch(directory, class_name, function, inputs):
    return subprocess.run(
        [_jdk_tool("java"), "-Xverify:all", "-Dfile.encoding=UTF-8",
         "-cp", str(directory), "FunnyRunner", class_name, function],
        input=inputs, capture_output=True, encoding="utf-8", errors="replace",
    )


def _write_class(path, contents):
    stream = NamedTemporaryFile(dir=path.parent, delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            stream.write(contents)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _build(args, class_bytes):
    with TemporaryDirectory(prefix="funny-runtime-") as temporary:
        runtime = Path(temporary)
        build_runtime(runtime)
        args.out.mkdir(parents=True, exist_ok=True)
        for name in RUNTIME_CLASSES:
            filename = name + ".class"
            _write_class(args.out / filename, (runtime / filename).read_bytes())
        target = args.out / (args.class_name + ".class")
        _write_class(target, class_bytes)
    print(target)
    return 0


def _run(args, module, class_bytes):
    function = next((item for item in module["functions"] if item["name"] == args.function), None)
    if function is None:
        raise ValueError(f"Функция {args.function} не найдена")
    inputs = encode_arguments(json.loads(args.args), function["params"])
    with TemporaryDirectory(prefix="funny-jvm-") as temporary:
        directory = Path(temporary)
        build_runtime(directory)
        (directory / (args.class_name + ".class")).write_bytes(class_bytes)
        process = launch(directory, args.class_name, args.function, inputs)
    sys.stdout.write(process.stdout)
    sys.stderr.write(process.stderr)
    return process.returncode


def _validate(args):
    pair = json.loads(args.pair.read_text(encoding="utf-8-sig"))
    query = build_query(pair)
    if args.smt_out is not None:
        args.smt_out.write_text(query + "(check-sat)\n", encoding="utf-8")
    result = solve_query(query, pair["inputs"])
    print(json.dumps(result, ensure_ascii=False))
    return {"unsat": 0, "sat": 1, "unknown": 2}[result["status"]]


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="funnyjvm", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="записать .class и классы рантайма")
    run = commands.add_parser("run", help="скомпилировать .funny и исполнить функцию на JVM")
    validate = commands.add_parser("validate", help="проверить эквивалентность пары блоков IR через Z3")
    validate.add_argument("pair", type=Path)
    validate.add_argument("--smt-out", type=Path, help="сохранить запрос в формате SMT-LIB")
    for command in (build, run):
        command.add_argument("source", type=Path)
        command.add_argument("--class", dest="class_name", default="FunnyModule")
        command.add_argument("--no-opt", action="store_true", help="использовать IR до оптимизаций")
        command.add_argument("--runtime-asserts", action="store_true",
                             help="проверять assert и assume на JVM")
    build.add_argument("--out", type=Path, default=Path("PROJECT/build"))
    run.add_argument("--function", default="main")
    run.add_argument("--args", default="[]", help="аргументы функции в JSON")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            return _validate(args)
        result = compile_source(args.source.read_text(encoding="utf-8-sig"), optimize=not args.no_opt)
        if not result.ok:
            for diagnostic in result.diagnostics:
                item = diagnostic.to_dict()
                code = f" [{item['code']}]" if item.get("code") else ""
                print(f"{item['line']}:{item['col']}: {item['phase']}{code}: {item['message']}",
                      file=sys.stderr)
            return 1
        class_bytes = emit_class(result.after, args.class_name, runtime_asserts=args.runtime_asserts)
        if args.command == "build":
            return _build(args, class_bytes)
        return _run(args, result.after, class_bytes)
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
