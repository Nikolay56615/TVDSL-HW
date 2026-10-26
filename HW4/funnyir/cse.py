"""Повторное использование уже вычисленных выражений внутри одного блока."""

from .ir import definitions
from .operations import i32


_BINARY = frozenset({"+", "-", "*", "==", "!=", "<", "<=", ">", ">="})
_UNARY = frozenset({"-", "not"})
_COMMUTATIVE = frozenset({"+", "*", "==", "!="})


class _BlockValues:
    def __init__(self):
        self.next_value = 0
        self.registers = {}
        self.holders = {}
        self.constants = {}
        self.expressions = {}

    def fresh(self):
        self.next_value += 1
        return self.next_value

    def assign(self, register, value):
        self.registers[register] = value
        self.holders.setdefault(value, set()).add(register)

    def forget(self, register):
        old = self.registers.pop(register, None)
        if old is not None:
            self.holders[old].remove(register)
            if not self.holders[old]:
                del self.holders[old]

    def operand(self, operand):
        if "const" in operand:
            value = operand["const"]
            # В Python True == 1, но в IR это константы разных типов.
            key = ("bool", value) if isinstance(value, bool) else ("int", i32(value))
            if key not in self.constants:
                self.constants[key] = self.fresh()
            return self.constants[key]
        register = operand["var"]
        if register not in self.registers:
            self.assign(register, self.fresh())
        return self.registers[register]

    def expression(self, instruction, values):
        op, operator = instruction["op"], instruction.get("operator")
        if op == "binary" and operator in _BINARY and len(values) == 2:
            if operator in _COMMUTATIVE:
                values = tuple(sorted(values))
            return (op, operator, values)
        if op == "unary" and operator in _UNARY and len(values) == 1:
            return (op, operator, values)
        return None

    def process(self, instruction):
        # Сначала читаем прежние значения: в x=x+1 запись происходит после чтения x.
        values = tuple(self.operand(arg) for arg in instruction.get("args", []))
        key = self.expression(instruction, values)
        result = None
        replacement = instruction
        if key is not None:
            if key not in self.expressions:
                self.expressions[key] = self.fresh()
            result = self.expressions[key]
            available = self.holders.get(result)
            if available:
                # Если t=a+b уже затёрт, берём сохранившуюся копию или считаем заново.
                source = min(available)
                replacement = {name: value for name, value in instruction.items()
                               if name not in {"operator", "args"}}
                replacement.update(op="copy", args=[{"var": source}])
        elif instruction["op"] == "copy" and len(values) == 1:
            result = values[0]

        written = definitions(instruction)
        for register in written:
            self.forget(register)
        for register in written:
            # Каждый результат call получает новый номер, включая все цели кортежа.
            value = result if register == instruction.get("dest") and result is not None else self.fresh()
            self.assign(register, value)
        return replacement


def eliminate_common_expressions(function: dict) -> None:
    """Заменить повтор a+b копией прежнего результата, если a и b не изменились.

    Копии переменных могут иметь разные имена временных регистров, но хранят
    одно значение. Поэтому для x=a+b; y=a+b второе сложение узнаётся и после
    разбиения исходных выражений на инструкции. На границе блока всё забываем.
    Деление, обращения к массивам, вызовы и spec остаются на своих местах.
    """
    for block in function["blocks"]:
        values = _BlockValues()
        block["instructions"] = [values.process(instruction)
                                 for instruction in block["instructions"]]
