"""Подстановка констант, упрощение выражений, CSE и удаление ненужных вычислений."""

from copy import deepcopy

from .analysis import analyze
from .cse import eliminate_common_expressions
from .ir import definitions, uses
from .operations import evaluate_binary, evaluate_unary, i32


def _constant(value):
    return value if isinstance(value, bool) else i32(value)


def _copy(instruction: dict, operand: dict) -> dict:
    """Заменить вычисление инструкцией copy, сохранив позицию в исходнике."""
    replacement = {
        key: value for key, value in instruction.items() if key not in {"operator", "args"}
    }
    replacement.update(op="copy", args=[deepcopy(operand)])
    return replacement


def _is_integer(operand: dict, value: int) -> bool:
    return (
        "const" in operand
        and isinstance(operand["const"], int)
        and not isinstance(operand["const"], bool)
        and i32(operand["const"]) == value
    )


def _simplify(instruction: dict) -> dict:
    if instruction["op"] != "binary":
        return instruction
    left, right = instruction["args"]
    operator = instruction["operator"]
    if operator in {"+", "-"} and _is_integer(right, 0):
        return _copy(instruction, left)
    if operator == "+" and _is_integer(left, 0):
        return _copy(instruction, right)
    if operator in {"*", "/"} and _is_integer(right, 1):
        return _copy(instruction, left)
    if operator == "*" and _is_integer(left, 1):
        return _copy(instruction, right)
    # Не заменяем x*0, 0/x и x/x константами: это может убрать
    # чтение переменной без значения или деление на ноль.
    return instruction


def _local_pass(function: dict, *, constants: bool, simplify: bool) -> None:
    for block in function["blocks"]:
        known = {}
        instructions = []
        for instruction in block["instructions"]:
            if constants:
                args = [
                    {"const": known[operand["var"]]}
                    if "var" in operand and operand["var"] in known
                    else operand
                    for operand in instruction.get("args", [])
                ]
                if "args" in instruction:
                    instruction["args"] = args
                if instruction["op"] in {"binary", "unary"} and all(
                    "const" in operand for operand in args
                ):
                    values = [_constant(operand["const"]) for operand in args]
                    try:
                        if instruction["op"] == "binary":
                            value = evaluate_binary(instruction["operator"], *values)
                        else:
                            value = evaluate_unary(instruction["operator"], *values)
                    except ZeroDivisionError:
                        # Сохраняем деление: ошибка должна возникнуть при выполнении инструкции.
                        pass
                    else:
                        instruction = _copy(instruction, {"const": value})
            if simplify:
                instruction = _simplify(instruction)
            # Аргументы уже обработаны с прежними значениями регистров.
            # После записи старое значение регистра больше нельзя подставлять.
            for destination in definitions(instruction):
                known.pop(destination, None)
            if (
                constants
                and instruction["op"] == "copy"
                and "const" in instruction["args"][0]
            ):
                known[instruction["dest"]] = _constant(instruction["args"][0]["const"])
            instructions.append(instruction)
        block["instructions"] = instructions


def _definitely_defined(function: dict, cfg: dict) -> dict:
    """Найти регистры, которым точно присвоено значение перед каждой инструкцией.

    Если x присвоен только в одной ветви if, после if он не считается заданным.
    На входе функции известны параметры. Для остальных блоков сначала допускаем
    все регистры, затем оставляем лишь общие для всех достижимых предшественников.
    """
    blocks = {block["label"]: block for block in function["blocks"]}
    parameters = {f"v:{parameter['name']}" for parameter in function["params"]}
    universe = set(parameters)
    block_defs = {}
    for label, block in blocks.items():
        block_defs[label] = set()
        for instruction in block["instructions"]:
            universe.update(uses(instruction))
            universe.update(definitions(instruction))
            block_defs[label].update(definitions(instruction))
    incoming = {
        label: set(parameters)
        if label == function["entry"]
        else set(universe) if node["reachable"] else set()
        for label, node in cfg.items()
    }
    outgoing = {label: incoming[label] | block_defs[label] for label in cfg}
    changed = True
    while changed:
        changed = False
        for label, node in cfg.items():
            if label == function["entry"]:
                before = set(parameters)
            elif not node["reachable"]:
                before = set()
            else:
                parents = [
                    outgoing[parent]
                    for parent in node["predecessors"]
                    if cfg[parent]["reachable"]
                ]
                before = set.intersection(*parents) if parents else set()
            after = before | block_defs[label]
            if before != incoming[label] or after != outgoing[label]:
                incoming[label], outgoing[label] = before, after
                changed = True
    points = {}
    for label, block in blocks.items():
        defined = set(incoming[label])
        points[label] = []
        for instruction in block["instructions"]:
            points[label].append(set(defined))
            defined.update(definitions(instruction))
    return points


def _removable(instruction: dict) -> bool:
    return instruction["op"] in {"copy", "unary"} or (
        instruction["op"] == "binary" and instruction["operator"] != "/"
    )


def _dce(function: dict) -> None:
    changed = True
    while changed:
        changed = False
        analysis = analyze(function)
        defined = _definitely_defined(function, analysis["cfg"])
        for block in function["blocks"]:
            label = block["label"]
            live = set(analysis["blocks"][label]["live_out"])
            retained = []
            for index in reversed(range(len(block["instructions"]))):
                instruction = block["instructions"][index]
                written, read = definitions(instruction), uses(instruction)
                if (
                    _removable(instruction)
                    and written
                    and not (written & live)
                    and read <= defined[label][index]
                ):
                    changed = True
                    continue
                retained.append(instruction)
                live = read | (live - written)
            block["instructions"] = list(reversed(retained))


def optimize_module(
    module: dict, *, constants: bool = True, simplify: bool = True,
    cse: bool = True, dce: bool = True
) -> dict:
    """Оптимизировать копию IR. Исходный модуль, контракты и формулы сохраняются."""
    result = deepcopy(module)
    for function in result["functions"]:
        if constants or simplify:
            _local_pass(function, constants=constants, simplify=simplify)
        if cse:
            eliminate_common_expressions(function)
        if dce:
            _dce(function)
    return result
