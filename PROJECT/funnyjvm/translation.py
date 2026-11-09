"""Проверка пары прямолинейных блоков HW4 через SMT."""

from HW4.funnyir.operations import i32


_BITVEC = "(_ BitVec 32)"
_BINARY = {"+": "bvadd", "-": "bvsub", "*": "bvmul", "/": "bvsdiv"}


def _operand(operand, registers):
    if isinstance(operand, dict):
        name = operand.get("var")
        if operand.keys() == {"var"} and isinstance(name, str):
            if name not in registers:
                raise ValueError(f"Регистр {name} прочитан до определения")
            return registers[name]
        if operand.keys() == {"const"} and type(operand["const"]) is int:
            return f"(_ bv{operand['const'] & 0xFFFFFFFF} 32)"
    raise ValueError("Операнд должен содержать var или целое const")


def _translate_block(block, prefix, inputs, lines):
    instructions = block.get("instructions") if isinstance(block, dict) else None
    if not isinstance(instructions, list) or not instructions:
        raise ValueError("У блока должен быть непустой список instructions")

    registers = dict(inputs)
    guards = []
    for index, instruction in enumerate(instructions):
        if not isinstance(instruction, dict) or not isinstance(instruction.get("args"), list):
            raise ValueError("У каждой инструкции должен быть список args")
        op, operator = instruction.get("op"), instruction.get("operator")
        operands = [_operand(item, registers) for item in instruction["args"]]
        if op == "return":
            if index != len(instructions) - 1 or not operands:
                raise ValueError("return должен быть последней инструкцией и возвращать значения")
            break

        if op == "copy" and len(operands) == 1:
            expression = operands[0]
        elif op == "unary" and operator == "-" and len(operands) == 1:
            expression = f"(bvneg {operands[0]})"
        elif op == "binary" and isinstance(operator, str) and operator in _BINARY and len(operands) == 2:
            left, right = operands
            expression = f"({_BINARY[operator]} {left} {right})"
            if operator == "/":
                guards.append(f"(not (= {right} (_ bv0 32)))")
        else:
            raise ValueError(f"Неподдерживаемая инструкция или число операндов: {op} {operator or ''}".rstrip())

        destination = instruction.get("dest")
        if not isinstance(destination, str) or not destination:
            raise ValueError("Инструкция должна записывать результат в dest")
        symbol = f"{prefix}_{index}"
        lines.append(f"(define-fun {symbol} () {_BITVEC} {expression})")
        registers[destination] = symbol
    else:
        raise ValueError("В конце блока нужен return")

    # Отдельно учитываем исключение JVM: деление битовых векторов само по себе его не моделирует.
    condition = f"(and true {' '.join(guards)})" if guards else "true"
    lines.append(f"(define-fun {prefix}_ok () Bool {condition})")
    return operands


def build_query(pair):
    """Построить запрос на существование входа, на котором блоки различаются."""
    names = pair.get("inputs") if isinstance(pair, dict) else None
    if not isinstance(names, list) or any(not isinstance(name, str) or not name for name in names):
        raise ValueError("inputs должен быть списком имён входных регистров")
    if len(set(names)) != len(names):
        raise ValueError("Входные регистры должны иметь разные имена")

    lines = ["(set-logic QF_BV)"]
    inputs = {name: f"arg_{index}" for index, name in enumerate(names)}
    for symbol in inputs.values():
        lines.append(f"(declare-fun {symbol} () {_BITVEC})")

    before = _translate_block(pair.get("before"), "before", inputs, lines)
    after = _translate_block(pair.get("after"), "after", inputs, lines)
    if len(before) != len(after):
        raise ValueError("Блоки должны возвращать одинаковое число значений")

    differences = " ".join(f"(not (= {a} {b}))" for a, b in zip(before, after))
    lines.append("(assert (or (xor before_ok after_ok)")
    lines.append(f"            (and before_ok after_ok (or false {differences}))))")
    return "\n".join(lines) + "\n"


def solve_query(query, input_names):
    try:
        import z3
    except ImportError as error:
        raise ValueError("Для validate установите Z3: python -m pip install z3-solver") from error

    solver = z3.Solver()
    solver.set(timeout=10_000)
    solver.from_string(query)
    status = solver.check()
    result = {"status": str(status)}
    if status == z3.sat:
        model = solver.model()
        result["inputs"] = {
            name: i32(model.eval(z3.BitVec(f"arg_{index}", 32), model_completion=True).as_long())
            for index, name in enumerate(input_names)
        }
    elif status == z3.unknown:
        result["reason"] = solver.reason_unknown()
    return result
