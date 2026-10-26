"""Таблицы функций, формул и переменных Funny."""

from dataclasses import dataclass


@dataclass
class VariableSymbol:
    name: str
    type: object
    declaration: dict
    readonly: bool = False


@dataclass
class CallableSymbol:
    name: str
    category: str
    params: list
    returns: list
    valid: bool = True


class Scope:
    """Хранит переменные этой области и ищет остальные имена во внешней."""

    def __init__(self, parent=None):
        self.parent = parent
        self.variables = {}

    def lookup(self, name):
        scope = self
        while scope is not None:
            if name in scope.variables:
                return scope.variables[name]
            scope = scope.parent
        return None

    def declare(self, symbol):
        # Например, параметр x запрещает объявить uses x или forall(x:int | ...).
        if self.lookup(symbol.name) is not None:
            return False
        self.variables[symbol.name] = symbol
        return True
