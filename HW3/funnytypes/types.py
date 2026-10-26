"""Проверка совместимости типов int, int[] и bool.

TypeVar обозначает пока неизвестный тип. Например, присваивание x = 1
связывает тип x с int. Если в присваивании найдена ошибка, эту связь отменяем.
"""

from dataclasses import dataclass


INT = "int"
ARRAY = "int[]"
BOOL = "bool"
ERROR = "error"
VARIABLE_TYPES = {INT, ARRAY}


@dataclass(eq=False)
class TypeVar:
    name: str
    binding: object = None


def resolve(value):
    """Проследить ссылки TypeVar: из T1 -> T2 -> int получить int."""
    while isinstance(value, TypeVar) and value.binding is not None:
        value = value.binding
    return value


def type_name(value):
    value = resolve(value)
    return ERROR if isinstance(value, TypeVar) else value


class UnificationError(ValueError):
    def __init__(self, left, right):
        self.left, self.right = left, right
        super().__init__("Несовместимые типы: %s и %s" % (left, right))


class Unification:
    """Запомнить изменения типов одного присваивания, чтобы их можно было отменить.

    Если x,y = f() ошибочно для y, тип x тоже не должен считаться выведенным.
    commit сохраняет изменения, rollback отменяет их.
    """

    def __init__(self):
        self.changes = []

    def unify(self, left, right):
        left, right = resolve(left), resolve(right)
        if left is right or left == right:
            return left
        if left == ERROR or right == ERROR:
            # После уже найденной ошибки не задаём тип переменной по ошибочному значению.
            return ERROR
        if isinstance(left, TypeVar):
            self.changes.append((left, left.binding))
            left.binding = right
            return right
        if isinstance(right, TypeVar):
            self.changes.append((right, right.binding))
            right.binding = left
            return left
        raise UnificationError(left, right)

    def rollback(self):
        for variable, previous in reversed(self.changes):
            variable.binding = previous
        self.changes.clear()

    def commit(self):
        self.changes.clear()


def unify(left, right):
    """Проверить совместимость двух типов и сразу сохранить результат."""
    transaction = Unification()
    result = transaction.unify(left, right)
    transaction.commit()
    return result
