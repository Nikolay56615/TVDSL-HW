"""Кодогенерация из IR HW4. На границах блоков стек JVM пуст."""

import re
from struct import pack

from HW4.funnyir.ir import definitions, uses
from HW4.funnyir.operations import i32

from .classfile import ClassFile, Code, u2


ARRAY = "LImmutableIntArray;"
DESCRIPTORS = {"int": "I", "int[]": ARRAY, "bool": "Z"}
ARITHMETIC = {"+": 0x60, "-": 0x64, "*": 0x68, "/": 0x6C}
COMPARISON = {"==": 0x9F, "!=": 0xA0, "<": 0xA1, ">=": 0xA2, ">": 0xA3, "<=": 0xA4}
RUNTIME_CLASSES = ("ImmutableIntArray", "FunnyRuntime", "FunnyRunner")


def _return_descriptor(returns):
    if len(returns) == 1:
        return DESCRIPTORS[returns[0]["type"]]
    if all(value["type"] == "int" for value in returns):
        return "[I"
    return "[Ljava/lang/Object;"


def _descriptor(function):
    if len(function["params"]) > 255:
        raise ValueError(f"Метод {function['name']} принимает более 255 параметров")
    arguments = "".join(DESCRIPTORS[param["type"]] for param in function["params"])
    return "(" + arguments + ")" + _return_descriptor(function["returns"])


def _formula_name(name):
    return "funny$formula$" + name


def emit_class(module, class_name="FunnyModule", *, runtime_asserts=False):
    """Вернуть байты одного public final класса с методами public static."""
    if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", class_name):
        raise ValueError("Имя JVM-класса должно быть простым идентификатором ASCII")
    if class_name.lower() in {name.lower() for name in RUNTIME_CLASSES}:
        raise ValueError("Имя класса занято средой исполнения Funny")
    functions = {function["name"]: function for function in module["functions"]}
    descriptors = {name: _descriptor(function) for name, function in functions.items()}
    formulas = {formula["name"]: formula for formula in module.get("formulas", [])}
    used_formulas = set()
    target = ClassFile(class_name)
    for function in functions.values():
        method = _Method(target.pool, class_name, function, functions, descriptors,
                         formulas, used_formulas, runtime_asserts)
        target.add_method(function["name"], descriptors[function["name"]],
                          method.compile(), method.max_stack, method.max_locals)
    emitted = set()
    while used_formulas - emitted:
        name = min(used_formulas - emitted)
        formula = formulas[name]
        function = {
            "name": _formula_name(name), "params": formula["params"],
            "returns": [{"type": "bool"}], "blocks": [],
            "types": {"v:" + param["name"]: param["type"] for param in formula["params"]},
        }
        method = _Method(target.pool, class_name, function, functions, descriptors,
                         formulas, used_formulas, runtime_asserts)
        method._predicate_value(formula["predicate"])
        method.code.emit(0xAC)  # ireturn
        target.add_method(function["name"], _descriptor(function), method.code.finish(),
                          method.max_stack, method.max_locals, access=0x000A)  # private static
        emitted.add(name)
    return target.encode()


class _Method:
    def __init__(self, pool, owner, function, functions, descriptors,
                 formulas, used_formulas, runtime_asserts):
        self.pool = pool
        self.owner = owner
        self.function = function
        self.functions = functions
        self.descriptors = descriptors
        self.formulas = formulas
        self.used_formulas = used_formulas
        self.runtime_asserts = runtime_asserts
        self.code = Code()
        self.types = function["types"]
        self.parameters = ["v:" + param["name"] for param in function["params"]]
        referenced = set(self.parameters)
        longest_call = 0
        for block in function["blocks"]:
            for instruction in block["instructions"]:
                if instruction["op"] != "spec" or runtime_asserts:
                    referenced.update(uses(instruction) | definitions(instruction))
                if instruction["op"] == "call":
                    longest_call = max(longest_call, len(instruction["args"]))
        registers = self.parameters + sorted(referenced - set(self.parameters))
        self.slots = {name: index for index, name in enumerate(registers)}
        # Временные значения HW4 создаются перед использованием. Для имён из
        # Funny нужен отдельный признак, чтобы начальный 0 JVM не скрыл ошибку.
        variables = [name for name in registers[len(self.parameters):] if name.startswith("v:")]
        self.flags = {name: len(registers) + index for index, name in enumerate(variables)}
        self.max_locals = len(registers) + len(self.flags)
        if self.max_locals > 65535:
            raise ValueError(f"Методу {function['name']} не хватает локальных слотов JVM")
        # Проверка очередного аргумента кладёт на стек флаг и строку позиции.
        # Упаковке кортежа и операциям с массивами хватает восьми слов.
        self.max_stack = max(8, longest_call + 2)

    def _integer(self, value):
        value = i32(int(value))
        if -1 <= value <= 5:
            self.code.emit(0x03 + value)  # iconst
        elif -128 <= value <= 127:
            self.code.emit(0x10, pack(">b", value))  # bipush
        elif -32768 <= value <= 32767:
            self.code.emit(0x11, pack(">h", value))  # sipush
        else:
            self.code.emit(0x13, u2(self.pool.integer(value)))  # ldc_w

    def _invoke(self, owner, name, descriptor, *, static=False):
        opcode = 0xB8 if static else 0xB6  # invokestatic / invokevirtual
        self.code.emit(opcode, u2(self.pool.method_ref(owner, name, descriptor)))

    def _load(self, argument, instruction):
        if "const" in argument:
            self._integer(argument["const"])
            return
        name = argument["var"]
        if name in self.flags:
            pos = instruction.get("pos", {})
            location = f"{name[2:]} at {pos.get('line', 1)}:{pos.get('col', 1)}"
            self.code.local(0x15, self.flags[name])  # iload
            self.code.emit(0x13, u2(self.pool.string(location)))
            self._invoke("FunnyRuntime", "requireDefined", "(ILjava/lang/String;)V", static=True)
        self.code.local(0x19 if self.types[name] == "int[]" else 0x15, self.slots[name])

    def _store(self, name):
        array = self.types[name] == "int[]"
        if array and name.startswith("v:"):
            self._invoke("FunnyRuntime", "copyArray", f"({ARRAY}){ARRAY}", static=True)
        self.code.local(0x3A if array else 0x36, self.slots[name])
        if name in self.flags:
            self._integer(1)
            self.code.local(0x36, self.flags[name])  # istore

    def _goto(self, label):
        self.code.jump(0xC8, label, wide=True)  # goto_w

    def _jump_if(self, truth, target):
        skip = object()
        self.code.jump(0x99 if truth else 0x9A, skip)  # ifeq / ifne
        self._goto(target)
        self.code.label(skip)

    def _binary(self, operator):
        if operator in ARITHMETIC:
            self.code.emit(ARITHMETIC[operator])
            return
        if operator not in COMPARISON:
            raise ValueError(f"Неизвестная бинарная операция JVM: {operator}")
        yes, end = object(), object()
        self.code.jump(COMPARISON[operator], yes)
        self._integer(0)
        self.code.jump(0xA7, end)  # goto
        self.code.label(yes)
        self._integer(1)
        self.code.label(end)

    def _unary(self, operator):
        if operator == "-":
            self.code.emit(0x74)  # ineg
        elif operator == "not":
            self._integer(1)
            self.code.emit(0x82)  # ixor
        else:
            raise ValueError(f"Неизвестная унарная операция JVM: {operator}")

    def _predicate_value(self, node, occupied=0):
        # Чтение переменной с проверкой может временно занять два места.
        self.max_stack = max(self.max_stack, occupied + 2)
        kind = node["kind"]
        if kind in {"Int", "Bool"}:
            self._integer(node["value"])
        elif kind == "Name":
            self._load({"var": "v:" + node["name"]}, node)
        elif kind == "Unary":
            self._predicate_value(node["operand"], occupied)
            self._unary(node["op"])
        elif kind == "Binary":
            operator = node["op"]
            self._predicate_value(node["left"], occupied)
            if operator in {"and", "or", "->"}:
                short, end = object(), object()
                self._jump_if(operator == "or", short)
                self._predicate_value(node["right"], occupied)
                self._goto(end)
                self.code.label(short)
                self._integer(operator != "and")
                self.code.label(end)
            else:
                self._predicate_value(node["right"], occupied + 1)
                self._binary(operator)
        elif kind == "Index":
            self._predicate_value(node["base"], occupied)
            self._predicate_value(node["index"], occupied + 1)
            self._invoke("ImmutableIntArray", "get", "(I)I")
        elif kind == "Call":
            for index, argument in enumerate(node["args"]):
                self._predicate_value(argument, occupied + index)
            name = node["name"]
            if name == "length":
                self._invoke("ImmutableIntArray", "length", "()I")
            elif name in self.formulas:
                self.used_formulas.add(name)
                signature = _descriptor({**self.formulas[name], "returns": [{"type": "bool"}]})
                self._invoke(self.owner, _formula_name(name), signature, static=True)
            else:
                self._invoke(self.owner, name, self.descriptors[name], static=True)
        else:
            pos = node["pos"]
            raise ValueError(f"{pos['line']}:{pos['col']}: --runtime-asserts "
                             f"не поддерживает выражение {kind}")

    def _runtime_spec(self, instruction):
        self._predicate_value(instruction["predicate"])
        passed = object()
        self._jump_if(True, passed)
        pos = instruction["pos"]
        for value in (instruction["kind"], f"{pos['line']}:{pos['col']}"):
            self.code.emit(0x13, u2(self.pool.string(value)))  # ldc_w
        self._invoke("FunnyRuntime", "specFailure",
                     "(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/AssertionError;", static=True)
        self.code.emit(0xBF)  # athrow
        self.code.label(passed)

    def _call(self, instruction):
        name = instruction["name"]
        returns = self.functions[name]["returns"]
        destinations = instruction["dests"]
        self._invoke(self.owner, name, self.descriptors[name], static=True)
        if len(destinations) == 1:
            self._store(destinations[0])
            return
        integer_tuple = _return_descriptor(returns) == "[I"
        for index, (destination, value) in enumerate(zip(destinations, returns)):
            self.code.emit(0x59)  # dup
            self._integer(index)
            self.code.emit(0x2E if integer_tuple else 0x32)  # iaload / aaload
            if not integer_tuple:
                kind = "ImmutableIntArray" if value["type"] == "int[]" else "java/lang/Integer"
                self.code.emit(0xC0, u2(self.pool.class_ref(kind)))  # checkcast
                if value["type"] == "int":
                    self._invoke(kind, "intValue", "()I")
            self._store(destination)
        self.code.emit(0x57)  # pop

    def _return(self, instruction):
        args = instruction["args"]
        returns = self.function["returns"]
        if len(returns) == 1:
            self._load(args[0], instruction)
            self.code.emit(0xB0 if returns[0]["type"] == "int[]" else 0xAC)
            return
        integer_tuple = _return_descriptor(returns) == "[I"
        self._integer(len(returns))
        if integer_tuple:
            self.code.emit(0xBC, b"\x0a")  # newarray int
        else:
            self.code.emit(0xBD, u2(self.pool.class_ref("java/lang/Object")))
        for index, (argument, value) in enumerate(zip(args, returns)):
            self.code.emit(0x59)  # dup
            self._integer(index)
            self._load(argument, instruction)
            if not integer_tuple and value["type"] == "int":
                self._invoke("java/lang/Integer", "valueOf", "(I)Ljava/lang/Integer;", static=True)
            self.code.emit(0x4F if integer_tuple else 0x53)  # iastore / aastore
        self.code.emit(0xB0)  # areturn

    def _instruction(self, instruction):
        op = instruction["op"]
        if op == "spec":
            if self.runtime_asserts:
                self._runtime_spec(instruction)
            return
        if op == "jump":
            self._goto(instruction["target"])
            return
        if op == "return":
            self._return(instruction)
            return
        for argument in instruction.get("args", []):
            self._load(argument, instruction)
        if op == "branch":
            # Условный переход имеет короткое смещение. Дальние цели идут через goto_w.
            no = object()
            self.code.jump(0x99, no)  # ifeq
            self._goto(instruction["then"])
            self.code.label(no)
            self._goto(instruction["else"])
            return
        if op == "call":
            self._call(instruction)
            return
        if op == "binary":
            self._binary(instruction["operator"])
        elif op == "unary":
            self._unary(instruction["operator"])
        elif op == "length":
            self._invoke("ImmutableIntArray", "length", "()I")
        elif op == "get":
            self._invoke("ImmutableIntArray", "get", "(I)I")
        elif op == "set":
            self._invoke("ImmutableIntArray", "with", f"(II){ARRAY}")
        elif op != "copy":
            raise ValueError(f"Неизвестная инструкция IR: {op}")
        self._store(instruction["dest"])

    def compile(self):
        for name, slot in self.slots.items():
            if slot < len(self.parameters):
                continue
            array = self.types[name] == "int[]"
            self.code.emit(0x01 if array else 0x03)  # aconst_null / iconst_0
            self.code.local(0x3A if array else 0x36, slot)
        for slot in self.flags.values():
            self._integer(0)
            self.code.local(0x36, slot)
        if self.function["entry"] != self.function["blocks"][0]["label"]:
            self._goto(self.function["entry"])
        for block in self.function["blocks"]:
            self.code.label(block["label"])
            for instruction in block["instructions"]:
                self._instruction(instruction)
        return self.code.finish()
