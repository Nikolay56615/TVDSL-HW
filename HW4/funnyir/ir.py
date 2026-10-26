"""Чтения и записи регистров, переходы между блоками, вывод IR и графов."""

import json


TERMINATORS = frozenset({"jump", "branch", "return"})


def successors(block):
    """Вернуть метки блоков, в которые ведёт последняя инструкция."""
    instructions = block.get("instructions", [])
    if not instructions:
        return []
    instruction = instructions[-1]
    if instruction["op"] == "jump":
        return [instruction["target"]]
    if instruction["op"] == "branch":
        return list(dict.fromkeys([instruction["then"], instruction["else"]]))
    return []


def _free_names(node, bound=frozenset()):
    """Найти переменные, которые предикат читает из функции.

    В forall(i:int | a[i] > x) это a и x; i объявлена самим квантором.
    """
    if isinstance(node, list):
        result = set()
        for item in node:
            result.update(_free_names(item, bound))
        return result
    if not isinstance(node, dict):
        return set()
    if node.get("kind") == "Name":
        name = node["name"]
        return set() if name in bound else {"v:" + name}
    if node.get("kind") == "Quantifier":
        binder = node["variable"]["name"]
        return _free_names(node.get("predicate"), bound | {binder})
    result = set()
    for child in node.values():
        result.update(_free_names(child, bound))
    return result


def uses(instruction):
    """Найти читаемые регистры, в том числе переменные из условия spec."""
    result = {argument["var"] for argument in instruction.get("args", [])
              if "var" in argument}
    if instruction["op"] == "spec":
        result.update(_free_names(instruction.get("predicate")))
    return result


def definitions(instruction):
    """Найти регистры, в которые инструкция записывает результаты."""
    result = set(instruction.get("dests", []))
    if "dest" in instruction:
        result.add(instruction["dest"])
    return result


def _operand_text(operand):
    if "var" in operand:
        return operand["var"]
    value = operand["const"]
    return str(value).lower() if isinstance(value, bool) else str(value)


def _predicate_text(node):
    if node is None:
        return "<нет>"
    kind = node.get("kind")
    if kind in {"Int", "Bool"}:
        return _operand_text({"const": node["value"]})
    if kind == "Name":
        return node["name"]
    if kind == "Unary":
        return "(%s %s)" % (node["op"], _predicate_text(node["operand"]))
    if kind == "Binary":
        return "(%s %s %s)" % (_predicate_text(node["left"]), node["op"],
                                _predicate_text(node["right"]))
    if kind == "Call":
        return "%s(%s)" % (node["name"], ", ".join(
            _predicate_text(arg) for arg in node.get("args", [])))
    if kind == "Index":
        return "%s[%s]" % (_predicate_text(node["base"]), _predicate_text(node["index"]))
    if kind == "ArrayUpdate":
        return "set(%s, %s, %s)" % tuple(_predicate_text(node[key])
                                        for key in ("base", "index", "value"))
    if kind == "Quantifier":
        binder = node["variable"]
        return "%s(%s:%s | %s)" % (node["quantifier"], binder["name"],
                                    binder["type"], _predicate_text(node["predicate"]))
    return json.dumps(node, ensure_ascii=False, sort_keys=True)


def _instruction_text(instruction):
    op = instruction["op"]
    arguments = ", ".join(_operand_text(arg) for arg in instruction.get("args", []))
    if op in {"copy", "length", "get", "set"}:
        text = "%s = %s %s" % (instruction["dest"], op, arguments)
    elif op in {"unary", "binary"}:
        text = "%s = %s %s %s" % (instruction["dest"], op,
                                      instruction["operator"], arguments)
    elif op == "call":
        text = "%s = call %s(%s)" % (", ".join(instruction["dests"]),
                                      instruction["name"], arguments)
    elif op == "spec":
        text = "spec %s %s" % (instruction["kind"],
                                _predicate_text(instruction["predicate"]))
    elif op == "jump":
        text = "jump " + instruction["target"]
    elif op == "branch":
        text = "branch %s ? %s : %s" % (arguments, instruction["then"], instruction["else"])
    elif op == "return":
        text = "return " + arguments
    else:
        text = json.dumps(instruction, ensure_ascii=False, sort_keys=True)
    pos = instruction.get("pos", {})
    return "%s  [%s:%s]" % (text.rstrip(), pos.get("line", 1), pos.get("col", 1))


def _variables_text(variables):
    return ", ".join("%s:%s" % (variable["name"], variable["type"])
                     for variable in variables)


def format_ir(module):
    """Вывести IR с позициями в исходнике и условиями requires/ensures/invariant."""
    lines = ["module IR v%s" % module.get("version", 1)]
    for formula in module.get("formulas", []):
        lines.append("formula %s(%s) => %s" % (
            formula["name"], _variables_text(formula.get("params", [])),
            _predicate_text(formula["predicate"])))
    for function in module.get("functions", []):
        lines.append("")
        lines.append("function %s(%s) returns %s" % (
            function["name"], _variables_text(function["params"]),
            _variables_text(function["returns"])))
        if function.get("locals"):
            lines.append("  locals " + _variables_text(function["locals"]))
        contracts = function.get("contracts", {})
        for kind in ("requires", "ensures"):
            if contracts.get(kind) is not None:
                lines.append("  %s %s" % (kind, _predicate_text(contracts[kind])))
        for invariant in contracts.get("invariants", []):
            lines.append("  invariant %s: %s" % (
                invariant["block"], _predicate_text(invariant["predicate"])))
        lines.append("  entry " + function["entry"])
        for block in function["blocks"]:
            lines.append("%s:" % block["label"])
            lines.extend("  " + _instruction_text(instruction)
                         for instruction in block["instructions"])
    return "\n".join(lines) + "\n"


def _dot_quote(value):
    return json.dumps(str(value), ensure_ascii=False)


def cfg_dot(function, cfg):
    """Граф CFG в DOT; недостижимые блоки отмечены серым цветом."""
    lines = ["digraph %s {" % _dot_quote("cfg_" + function["name"]),
             "  node [shape=box, fontname=\"monospace\"];", "  rankdir=TB;"]
    for block in function["blocks"]:
        label = block["label"]
        body = label + ":\n" + "\n".join(
            _instruction_text(instruction) for instruction in block["instructions"])
        style = ""
        if not cfg.get(label, {}).get("reachable", True):
            style = ', style="filled", fillcolor="#eeeeee"'
        lines.append("  %s [label=%s%s];" % (_dot_quote(label), _dot_quote(body), style))
    for block in function["blocks"]:
        label = block["label"]
        targets = cfg.get(label, {}).get("successors", successors(block))
        for target in targets:
            lines.append("  %s -> %s;" % (_dot_quote(label), _dot_quote(target)))
    lines.append("}")
    return "\n".join(lines) + "\n"


def interference_dot(function, graph, colors):
    """Неориентированный граф конфликтов с номерами цветов и без петель."""
    palette = ("#cce5ff", "#d8f3dc", "#ffe5b4", "#ead5ff", "#ffcdd2", "#c8f0ec")
    registers = set(graph) | set(colors)
    for neighbors in graph.values():
        registers.update(neighbors)
    lines = ["graph %s {" % _dot_quote("interference_" + function["name"]),
             '  node [shape=ellipse, fontname="monospace"];']
    for register in sorted(registers):
        color = colors.get(register)
        label = register if color is None else "%s [color=%s]" % (register, color)
        style = "" if color is None else ', style="filled", fillcolor=%s' % _dot_quote(
            palette[color % len(palette)])
        lines.append("  %s [label=%s%s];" % (_dot_quote(register), _dot_quote(label), style))
    edges = {tuple(sorted((register, neighbor)))
             for register, neighbors in graph.items() for neighbor in neighbors
             if register != neighbor}
    for left, right in sorted(edges):
        lines.append("  %s -- %s;" % (_dot_quote(left), _dot_quote(right)))
    lines.append("}")
    return "\n".join(lines) + "\n"
