"""Выполнение IR для сравнения результатов до и после оптимизаций."""

from .operations import evaluate_binary, evaluate_unary, i32


class IRRuntimeError(Exception):
    def __init__(self, code, message, pos=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.pos = dict(pos or {"line": 1, "col": 1})

    def to_dict(self):
        return {"code": self.code, "message": self.message, "pos": self.pos}


def _plain(value):
    return [_plain(item) for item in value] if isinstance(value, tuple) else value


def _argument(value, expected, name):
    if expected == "int" and type(value) is int:
        return i32(value)
    if expected == "int[]" and isinstance(value, (list, tuple)):
        if all(type(item) is int for item in value):
            return tuple(i32(item) for item in value)
    if expected == "bool" and type(value) is bool:
        return value
    raise IRRuntimeError("argument_type", "Аргумент %r должен иметь тип %s" % (name, expected))


class _Machine:
    def __init__(self, module, max_steps, max_depth):
        self.functions = {function["name"]: function for function in module["functions"]}
        self.max_steps = max_steps
        self.max_depth = max_depth
        self.steps = 0

    @staticmethod
    def _value(operand, registers, pos):
        if set(operand) == {"const"}:
            value = operand["const"]
            if type(value) is bool:
                return value
            if type(value) is int:
                return i32(value)
            raise IRRuntimeError("invalid_ir", "В IR ожидалась целая или логическая константа", pos)
        if set(operand) != {"var"}:
            raise IRRuntimeError("invalid_ir", "Неверный операнд IR", pos)
        name = operand["var"]
        if name not in registers:
            raise IRRuntimeError("uninitialized", "Чтение неинициализированной переменной %r" % name, pos)
        return registers[name]

    @staticmethod
    def _array(value, pos):
        if not isinstance(value, tuple):
            raise IRRuntimeError("invalid_ir", "Ожидался массив int[]", pos)
        return value

    @staticmethod
    def _index(array, index, pos):
        if type(index) is not int:
            raise IRRuntimeError("invalid_ir", "Индекс должен быть целым", pos)
        # В Python отрицательный индекс допустим, в Funny и JVM — ошибка.
        if index < 0 or index >= len(array):
            raise IRRuntimeError("array_bounds", "Индекс %d вне массива длины %d" % (index, len(array)), pos)

    def call(self, name, arguments, depth=0, call_pos=None):
        if depth >= self.max_depth:
            raise IRRuntimeError("recursion_limit", "Превышена допустимая глубина вызовов", call_pos)
        function = self.functions.get(name)
        if function is None:
            raise IRRuntimeError("unknown_function", "Неизвестная функция %r" % name, call_pos)
        params = function["params"]
        if len(arguments) != len(params):
            raise IRRuntimeError("argument_count", "Функция %r ожидает %d аргументов, получено %d"
                                 % (name, len(params), len(arguments)), call_pos)
        registers = {"v:" + parameter["name"]: _argument(value, parameter["type"], parameter["name"])
                     for parameter, value in zip(params, arguments)}
        blocks = {block["label"]: block for block in function["blocks"]}
        label = function["entry"]
        while True:
            if label not in blocks:
                raise IRRuntimeError("invalid_ir", "Неизвестный блок %r" % label, call_pos)
            jumped = False
            for instruction in blocks[label]["instructions"]:
                pos = instruction.get("pos", {"line": 1, "col": 1})
                self.steps += 1
                if self.steps > self.max_steps:
                    raise IRRuntimeError("step_limit", "Превышен лимит шагов IR", pos)
                op = instruction["op"]
                args = [self._value(arg, registers, pos) for arg in instruction.get("args", [])]
                try:
                    if op == "copy":
                        registers[instruction["dest"]] = args[0]
                    elif op == "unary":
                        registers[instruction["dest"]] = evaluate_unary(instruction["operator"], args[0])
                    elif op == "binary":
                        registers[instruction["dest"]] = evaluate_binary(instruction["operator"], *args)
                    elif op == "length":
                        registers[instruction["dest"]] = len(self._array(args[0], pos))
                    elif op in {"get", "set"}:
                        array, index = self._array(args[0], pos), args[1]
                        self._index(array, index, pos)
                        if op == "get":
                            registers[instruction["dest"]] = array[index]
                        else:
                            registers[instruction["dest"]] = array[:index] + (i32(args[2]),) + array[index + 1:]
                    elif op == "call":
                        values = self.call(instruction["name"], args, depth + 1, pos)
                        if len(values) != len(instruction["dests"]):
                            raise IRRuntimeError("invalid_ir", "Число целей call не совпало с возвратами", pos)
                        registers.update(zip(instruction["dests"], values))
                    elif op == "jump":
                        label, jumped = instruction["target"], True
                        break
                    elif op == "branch":
                        if type(args[0]) is not bool:
                            raise IRRuntimeError("invalid_ir", "У branch ожидался bool", pos)
                        label = instruction["then"] if args[0] else instruction["else"]
                        jumped = True
                        break
                    elif op == "return":
                        if len(args) != len(function["returns"]):
                            raise IRRuntimeError("invalid_ir", "Неверное число результатов return", pos)
                        return args
                    elif op == "spec":
                        pass
                    else:
                        raise IRRuntimeError("invalid_ir", "Неизвестная инструкция %r" % op, pos)
                except ZeroDivisionError as error:
                    raise IRRuntimeError("division_by_zero", "Деление на ноль", pos) from error
                except (KeyError, IndexError, TypeError, ValueError) as error:
                    raise IRRuntimeError("invalid_ir", "Повреждённая инструкция IR: %s" % error, pos) from error
            if not jumped:
                raise IRRuntimeError("invalid_ir", "Блок %r не завершён переходом или return" % label, call_pos)


def execute(module, function="main", arguments=None, *, max_steps=100000, max_depth=128):
    """Выполнить функцию и вернуть список её результатов.

    Массивы возвращаются обычными списками. Внутри они хранятся как кортежи:
    обновление создаёт новый массив и не меняет массив вызывающего кода.
    """
    if type(max_steps) is not int or max_steps < 1 or type(max_depth) is not int or max_depth < 1:
        raise ValueError("Лимиты шагов и глубины должны быть положительными целыми")
    if arguments is None:
        arguments = []
    if not isinstance(arguments, (list, tuple)):
        raise IRRuntimeError("argument_type", "Аргументы функции должны быть списком")
    machine = _Machine(module, max_steps, max_depth)
    try:
        values = machine.call(function, arguments)
        return [_plain(value) for value in values]
    except RecursionError as error:
        raise IRRuntimeError("recursion_limit", "Достигнут предел стека Python") from error
