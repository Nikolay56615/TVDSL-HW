"""Проверка имён и типов в дереве программы, полученном из HW2.

Сначала собираем объявления всех функций и формул, затем проверяем их тела.
Так можно вызвать функцию раньше её объявления в файле.
"""

from copy import deepcopy
from dataclasses import dataclass

from .symbols import CallableSymbol, Scope, VariableSymbol
from .types import (ARRAY, BOOL, ERROR, INT, VARIABLE_TYPES, TypeVar,
                    Unification, UnificationError, resolve, type_name)


@dataclass
class Diagnostic:
    phase: str
    line: int
    col: int
    message: str
    code: str

    def to_dict(self):
        return {"phase": self.phase, "line": self.line, "col": self.col,
                "message": self.message, "code": self.code}


@dataclass
class CheckResult:
    ast: dict
    diagnostics: list

    @property
    def ok(self):
        return not self.diagnostics

    def to_dict(self):
        return {"ok": self.ok, "ast": self.ast,
                "diagnostics": [error.to_dict() for error in self.diagnostics]}


_ARITHMETIC = {"+", "-", "*", "/"}
_COMPARISONS = {"==", "!=", "<", "<=", ">", ">="}
_LOGICAL = {"and", "or", "->"}


class _Checker:
    def __init__(self, ast):
        self.ast = ast
        self.diagnostics = []
        self.reported = set()
        self.callables = {"length": CallableSymbol("length", "Function", [ARRAY], [INT])}

    def _error(self, node, code, message):
        pos = node.get("pos", {}) if isinstance(node, dict) else {}
        line, col = pos.get("line", 1), pos.get("col", 1)
        # Парсер превращает a[i] = v в a = ArrayUpdate(a, i, v).
        # Ошибку в имени a можно найти дважды; второе сообщение пропускаем.
        key = (code, line, col, message)
        if key not in self.reported:
            self.reported.add(key)
            self.diagnostics.append(Diagnostic("semantic", line, col, message, code))

    @staticmethod
    def _annotate(node, result):
        if isinstance(node, dict):
            node["inferred_type"] = result
        return result

    @staticmethod
    def _declared_type(declaration):
        value = declaration.get("type")
        return value if value in VARIABLE_TYPES else ERROR

    def _signature(self, declaration):
        params = [self._declared_type(var) for var in declaration.get("params", [])]
        returns = ([BOOL] if declaration["kind"] == "Formula" else
                   [self._declared_type(var) for var in declaration.get("returns", [])])
        names = [var["name"] for var in declaration.get("params", [])]
        if declaration["kind"] == "Function":
            names += [var["name"] for var in declaration.get("returns", [])]
        valid = ERROR not in params + returns and len(names) == len(set(names))
        if declaration["kind"] == "Function" and not returns:
            valid = False
        declaration["signature"] = {"params": params, "returns": returns}
        return CallableSymbol(declaration["name"], declaration["kind"], params, returns, valid)

    def _register(self, declarations):
        for declaration in declarations:
            if declaration.get("kind") not in {"Function", "Formula"}:
                continue
            symbol = self._signature(declaration)
            if symbol.name in self.callables:
                self._error(declaration, "duplicate_name",
                            "Повторное глобальное имя %r" % symbol.name)
            else:
                self.callables[symbol.name] = symbol

    def _declare(self, declaration, scope, *, readonly=False, infer=False):
        declared = declaration.get("type")
        if declared is None and infer:
            value = TypeVar(declaration["name"])
        elif declared in VARIABLE_TYPES:
            value = declared
        else:
            self._error(declaration, "invalid_type",
                        "У переменной %r ожидался явный тип int или int[], получен %r"
                        % (declaration["name"], declared))
            value = ERROR
        symbol = VariableSymbol(declaration["name"], value, declaration, readonly)
        self._annotate(declaration, type_name(value))
        accepted = scope.declare(symbol)
        if not accepted:
            self._error(declaration, "duplicate_name",
                        "Повторное имя переменной %r" % symbol.name)
        return symbol, accepted

    def _check_declaration(self, declaration):
        # В requires доступны только параметры функции.
        params = Scope()
        for parameter in declaration.get("params", []):
            self._declare(parameter, params, readonly=True)
        if declaration["kind"] == "Formula":
            predicate = declaration.get("predicate")
            self._expect(self._expression(predicate, params, "predicate"), BOOL, predicate)
            return

        # В ensures доступны параметры и возвращаемые переменные.
        results = Scope(params)
        for result in declaration.get("returns", []):
            self._declare(result, results)
        if not declaration.get("returns"):
            self._error(declaration, "invalid_signature", "У функции требуется хотя бы один возврат")
        # Локальные из uses доступны в теле, но не в requires и ensures.
        body_scope = Scope(results)
        locals_ = [self._declare(var, body_scope, infer=True)
                   for var in declaration.get("locals", [])]
        requires, ensures = declaration.get("requires"), declaration.get("ensures")
        if requires is not None:
            self._expect(self._expression(requires, params, "predicate"), BOOL, requires)
        if ensures is not None:
            self._expect(self._expression(ensures, results, "predicate"), BOOL, ensures)
        self._statement(declaration.get("body"), body_scope)
        for symbol, accepted in locals_:
            value = resolve(symbol.type)
            self._annotate(symbol.declaration, type_name(value))
            if accepted and isinstance(value, TypeVar):
                self._error(symbol.declaration, "unresolved_type",
                            "Не удалось вывести тип локальной переменной %r: нет корректного присваивания"
                            % symbol.name)

    def run(self):
        declarations = self.ast.get("declarations", [])
        self._register(declarations)
        for declaration in declarations:
            if declaration.get("kind") in {"Function", "Formula"}:
                self._check_declaration(declaration)
        return CheckResult(self.ast, self.diagnostics)

    def _expect(self, actual, expected, node):
        if actual == ERROR:
            return False
        if actual != expected:
            found = ", ".join(actual) if isinstance(actual, list) else actual
            self._error(node, "type_mismatch", "Ожидался тип %s, получен %s" % (expected, found))
            return False
        return True

    def _name(self, node, scope, update_target=None):
        symbol = scope.lookup(node["name"])
        if symbol is None:
            self._error(node, "unknown_variable", "Неизвестная переменная %r" % node["name"])
            return ERROR
        value = resolve(symbol.type)
        if isinstance(value, TypeVar):
            # Из a[i] = v можно вывести тип a: int[], если всё присваивание верно.
            # Здесь разрешаем чтение a только для обновления массива.
            # Чтение справа, как в a[i] = a[0], всё ещё требует известного типа.
            if symbol is update_target:
                return ARRAY
            self._error(node, "unresolved_type",
                        "Тип локальной переменной %r ещё не выведен" % symbol.name)
            return ERROR
        return value

    def _call(self, node, scope, context, allow_tuple):
        before = len(self.diagnostics)
        actuals = [self._expression(arg, scope, "value") for arg in node.get("args", [])]
        symbol = self.callables.get(node["name"])
        if symbol is None:
            self._error(node, "unknown_callable", "Неизвестная функция или формула %r" % node["name"])
            return ERROR
        if symbol.category == "Formula" and context != "predicate":
            self._error(node, "callable_context", "Формула %r разрешена только в предикатах" % symbol.name)
        elif symbol.category == "Function" and context != "value":
            self._error(node, "callable_context",
                        "Функция %r используется как значение, а не как предикат" % symbol.name)
        if len(actuals) != len(symbol.params):
            self._error(node, "argument_count", "Вызов %r ожидает %d аргументов, получено %d"
                        % (symbol.name, len(symbol.params), len(actuals)))
        for arg, actual, expected in zip(node.get("args", []), actuals, symbol.params):
            if expected != ERROR:
                self._expect(actual, expected, arg)
        if len(symbol.returns) != 1 and not allow_tuple:
            self._error(node, "result_count",
                        "Функция %r возвращает %d значений; требуется присваивание кортежа"
                        % (symbol.name, len(symbol.returns)))
        if (len(self.diagnostics) != before or not symbol.valid or ERROR in actuals):
            return ERROR
        return list(symbol.returns) if len(symbol.returns) != 1 else symbol.returns[0]

    def _expression(self, node, scope, context="value", *, allow_tuple=False, update_target=None):
        if node is None:
            return ERROR
        kind = node.get("kind")
        value = ERROR
        if kind == "Int":
            value = INT
        elif kind == "Bool":
            value = BOOL
        elif kind == "Name":
            value = self._name(node, scope, update_target)
        elif kind == "Call":
            value = self._call(node, scope, context, allow_tuple)
        elif kind == "Unary":
            operation = node.get("op")
            expected = INT if operation == "-" else BOOL
            child_context = "value" if operation == "-" else (
                "predicate" if context == "predicate" else "condition")
            operand = self._expression(node.get("operand"), scope, child_context)
            if operation not in {"-", "not"}:
                self._error(node, "unsupported_node", "Неизвестная унарная операция %r" % operation)
            elif self._expect(operand, expected, node.get("operand")):
                value = expected
        elif kind == "Binary":
            operation = node.get("op")
            expected = BOOL if operation in _LOGICAL else INT
            child_context = ("predicate" if context == "predicate" else "condition") \
                if operation in _LOGICAL else "value"
            left = self._expression(node.get("left"), scope, child_context)
            right = self._expression(node.get("right"), scope, child_context)
            valid_left = self._expect(left, expected, node.get("left"))
            valid_right = self._expect(right, expected, node.get("right"))
            if operation not in _ARITHMETIC | _COMPARISONS | _LOGICAL:
                self._error(node, "unsupported_node", "Неизвестная бинарная операция %r" % operation)
            elif valid_left and valid_right:
                value = INT if operation in _ARITHMETIC else BOOL
        elif kind in {"Index", "ArrayUpdate"}:
            base = self._expression(node.get("base"), scope, "value", update_target=update_target)
            index = self._expression(node.get("index"), scope, "value")
            base_valid = self._expect(base, ARRAY, node.get("base"))
            index_valid = self._expect(index, INT, node.get("index"))
            value_valid = True
            if kind == "ArrayUpdate":
                item_node = node.get("value")
                # Для a[i][j] = v парсер строит два вложенных ArrayUpdate.
                # Разрешение вывести тип a передаём только вложенному обновлению,
                # а не выражению v. Проверка типов ниже отклонит второй индекс.
                inner_target = update_target if item_node and item_node.get("kind") == "ArrayUpdate" else None
                item = self._expression(item_node, scope, "value", update_target=inner_target)
                value_valid = self._expect(item, INT, item_node)
            if base_valid and index_valid and value_valid:
                value = ARRAY if kind == "ArrayUpdate" else INT
        elif kind == "Quantifier":
            child_scope = Scope(scope)
            binder, accepted = self._declare(node["variable"], child_scope, readonly=True)
            predicate = self._expression(node.get("predicate"), child_scope, "predicate")
            valid = self._expect(predicate, BOOL, node.get("predicate"))
            if context != "predicate":
                self._error(node, "predicate_context", "Кванторы разрешены только в предикатах")
            elif valid and accepted and binder.type != ERROR:
                value = BOOL
        elif kind != "Error":
            self._error(node, "unsupported_node", "Неизвестное выражение %r" % kind)
        return self._annotate(node, value)

    def _target(self, node, scope):
        symbol = scope.lookup(node["name"])
        if symbol is None:
            self._error(node, "unknown_variable", "Неизвестная переменная %r" % node["name"])
            self._annotate(node, ERROR)
            return None
        self._annotate(node, type_name(symbol.type))
        if symbol.readonly:
            self._error(node, "readonly_assignment", "Параметр %r доступен только для чтения" % symbol.name)
        return symbol

    def _assignment(self, node, scope):
        before = len(self.diagnostics)
        targets = node.get("targets", [])
        symbols = [self._target(target, scope) for target in targets]
        rhs = node.get("value")
        tuple_assignment = len(targets) > 1
        special_base = symbols[0] if len(symbols) == 1 and rhs and rhs.get("kind") == "ArrayUpdate" else None
        value = self._expression(rhs, scope, "value", allow_tuple=tuple_assignment,
                                 update_target=special_base)
        values = value if isinstance(value, list) else [value]
        if tuple_assignment and rhs and rhs.get("kind") != "Call":
            self._error(rhs, "result_count", "Присваивание кортежа требует вызова функции")
        if value != ERROR and len(values) != len(targets):
            self._error(rhs, "result_count", "В присваивании %d переменных, а результатов %d"
                        % (len(targets), len(values)))
        transaction = Unification()
        for target, symbol, actual in zip(targets, symbols, values):
            if actual == ERROR or symbol is None:
                continue
            if actual not in VARIABLE_TYPES:
                self._error(rhs, "type_mismatch",
                            "Переменной можно присвоить int или int[], получен %s" % actual)
                continue
            try:
                transaction.unify(symbol.type, actual)
            except UnificationError as error:
                location = target if tuple_assignment else rhs
                self._error(location, "type_mismatch", "Переменная %r: ожидался тип %s, получен %s"
                            % (symbol.name, error.left, error.right))
        if len(self.diagnostics) == before and value != ERROR and len(values) == len(targets):
            transaction.commit()
        else:
            transaction.rollback()
        for target, symbol in zip(targets, symbols):
            if symbol is not None:
                self._annotate(target, type_name(symbol.type))

    def _statement(self, node, scope):
        if node is None:
            return
        kind = node.get("kind")
        if kind == "Block":
            for statement in node.get("statements", []):
                self._statement(statement, scope)
        elif kind == "Assign":
            self._assignment(node, scope)
        elif kind in {"If", "While"}:
            condition = node.get("condition")
            self._expect(self._expression(condition, scope, "condition"), BOOL, condition)
            if kind == "If":
                self._statement(node.get("then"), scope)
                self._statement(node.get("else"), scope)
            else:
                invariant = node.get("invariant")
                if invariant is not None:
                    self._expect(self._expression(invariant, scope, "predicate"), BOOL, invariant)
                self._statement(node.get("body"), scope)
        elif kind in {"Assert", "Assume"}:
            predicate = node.get("predicate")
            self._expect(self._expression(predicate, scope, "predicate"), BOOL, predicate)
        elif kind != "Error":
            self._error(node, "unsupported_node", "Неизвестный оператор %r" % kind)


def check_ast(ast):
    """Проверить копию дерева HW2 и вернуть её с типами и списком ошибок."""
    return _Checker(deepcopy(ast)).run()
