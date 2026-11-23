"""Генерация проверяющей программы Spin и разбор результатов её запуска."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory, mkdtemp
import time


ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "models" / "protocol.pml"
CASES = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
PROPERTIES = {
    "exclusive": "Подтверждение и тайм-аут не возникают одновременно",
    "requested": "Результат относится к отправленному запросу",
    "retry_bound": "Число повторов не превышает лимит",
    "pending_clean": "Ожидающий запрос отправлен и ещё не завершён",
    "response": "Каждый ожидающий запрос получает подтверждение или тайм-аут",
    "next_request": "После завершения клиент отправляет следующий запрос",
}


def executable(value):
    path = shutil.which(value)
    if path is None:
        raise ValueError(f"Не найдена программа {value}. Укажите путь через --spin или --cc")
    return str(Path(path).resolve())


def run(command, directory, timeout):
    try:
        return subprocess.run(
            command, cwd=directory, capture_output=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"Превышено время запуска {command[0]} ({timeout} с)") from error


def save_log(path, command, process, cwd):
    text = f"Автоматический запуск HW5 из {cwd}\n"
    text += subprocess.list2cmdline(command) + "\n\n"
    text += process.stdout + process.stderr
    path.write_text(text, encoding="utf-8")


def parse_verification(text):
    """Вернуть исход проверки. Прерванный поиск нельзя считать доказательством."""
    errors = re.search(r"\berrors:\s*(\d+)", text)
    if errors is None or "Full statespace search" not in text:
        raise ValueError("Spin не выдал результат полного поиска")
    if re.search(r"depth too small|out of memory|VECTORSZ|error:|interrupted", text, re.IGNORECASE):
        raise ValueError("Проверка Spin прервана. Смотрите лог запуска")
    count = int(errors[1])
    if count:
        if "acceptance cycle" in text:
            kind = "cycle"
        elif "assertion violated" in text:
            kind = "state"
        else:
            raise ValueError("Spin нашёл ошибку, не относящуюся к проверяемому свойству")
        return {"holds": False, "counterexample": kind}
    if "Search not completed" in text:
        raise ValueError("Поиск Spin не завершён")
    return {"holds": True, "counterexample": None}


def verify(variant, retries, properties, out, *, spin="spin", cc="gcc",
           por=True, depth=10000, timeout=60, model=MODEL):
    spin, cc = executable(spin), executable(cc)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    directory = Path(mkdtemp(prefix=f"{variant}-r{retries}-", dir=out)).resolve()
    defines = f"#define MAX_RETRIES {retries}\n"
    if CASES[variant]["define"]:
        defines += f"#define {CASES[variant]['define']}\n"
    source = defines + Path(model).read_text(encoding="utf-8")
    (directory / "protocol.pml").write_text(source, encoding="utf-8")
    versions = {}
    for name, command in (("spin", [spin, "-V"]), ("cc", [cc, "--version"])):
        process = run(command, directory, timeout)
        if process.returncode:
            raise ValueError(f"Не удалось запустить {name} (код {process.returncode})")
        versions[name] = (process.stdout + process.stderr).strip().splitlines()[0]

    results = []
    with TemporaryDirectory(prefix="hw5-spin-") as temporary:
        build = Path(temporary)
        (build / "protocol.pml").write_text(source, encoding="utf-8")
        # Spin сам вызывает C-препроцессор. Передаём тот же компилятор, что собирает pan.
        preprocess = subprocess.list2cmdline([cc, "-E", "-x", "c"])
        generate = [spin, "-P" + preprocess, "-a", "protocol.pml"]
        process = run(generate, build, timeout)
        save_log(directory / "generate.log", generate, process, build)
        if process.returncode or not (build / "pan.c").is_file():
            raise ValueError(f"Не удалось обработать модель. Лог в {directory / 'generate.log'}")
        pan = build / ("pan.exe" if os.name == "nt" else "pan")
        compile_command = [cc, "-O2", "-o", str(pan), "pan.c"]
        if not por:
            compile_command.insert(1, "-DNOREDUCE")
        process = run(compile_command, build, timeout)
        save_log(directory / "compile.log", compile_command, process, build)
        if process.returncode or not pan.is_file():
            raise ValueError(f"Не удалось собрать pan. Лог в {directory / 'compile.log'}")

        for name in properties:
            property_directory = directory / name
            property_directory.mkdir()
            shutil.copy2(directory / "protocol.pml", property_directory / "protocol.pml")
            command = [str(pan), "-a", "-b", "-m" + str(depth), "-w18", "-N", name]
            start = time.perf_counter()
            process = run(command, property_directory, timeout)
            elapsed = time.perf_counter() - start
            save_log(property_directory / "verify.log", command, process, property_directory)
            if process.returncode:
                raise ValueError(f"Ошибка pan (код {process.returncode}). Лог в {property_directory}")
            try:
                result = parse_verification(process.stdout + process.stderr)
            except ValueError as error:
                raise ValueError(f"{error}. Лог в {property_directory}") from error
            result.update(property=name, seconds=round(elapsed, 6))
            stored = re.search(r"([\d.e+]+) states, stored", process.stdout)
            result["states"] = int(float(stored[1])) if stored else None
            result["trace"] = None
            if not result["holds"]:
                trail = property_directory / "protocol.pml.trail"
                if not trail.is_file():
                    raise ValueError(f"Spin не сохранил контрпример для {name}")
                replay = [spin, "-P" + preprocess, "-t", "-p", "-g", "protocol.pml"]
                trace = run(replay, property_directory, timeout)
                save_log(property_directory / "replay.log", replay, trace, property_directory)
                trace_text = trace.stdout + trace.stderr
                marker = "START OF CYCLE" if result["counterexample"] == "cycle" else "assertion violated"
                if trace.returncode or "trail ends after" not in trace_text or marker not in trace_text:
                    raise ValueError(f"Не удалось воспроизвести контрпример. Лог в {property_directory}")
                trace_path = property_directory / "trace.txt"
                trace_path.write_text(trace_text, encoding="utf-8")
                result["trace"] = str(trace_path)
            results.append(result)

    report = {
        "variant": variant, "max_retries": retries, "por": por,
        "fairness": False, "depth_limit": depth, "versions": versions,
        "model": str(Path(model).resolve()),
        "results": results,
    }
    (directory / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return report, directory
