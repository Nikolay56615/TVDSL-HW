"""Перевод проверенного дерева HW3 в инструкции IR.

Выражения разбиваются на отдельные вычисления, условия и циклы — на блоки
с переходами. В конце функции добавляется возврат переменных из returns.
"""

from copy import deepcopy


def _position(node):
    position = node.get("pos", {})
    return {"line": position.get("line", 1), "col": position.get("col", 1)}


def _variable(declaration):
    return {"name": declaration["name"],
            "type": declaration.get("inferred_type") or declaration["type"]}


class _FunctionLowerer:
    def __init__(self, declaration):
        self.declaration = declaration
        self.next_temporary = 0
        self.function = {
            "name": declaration["name"],
            "params": [_variable(item) for item in declaration.get("params", [])],
            "returns": [_variable(item) for item in declaration.get("returns", [])],
            "locals": [_variable(item) for item in declaration.get("locals", [])],
            "types": {}, "entry": "B0", "blocks": [],
            "contracts": {"requires": deepcopy(declaration.get("requires")),
                          "ensures": deepcopy(declaration.get("ensures")),
                          "invariants": []},
        }
        for group in ("params", "returns", "locals"):
            for variable in self.function[group]:
                self.function["types"]["v:" + variable["name"]] = variable["type"]
        self.current = self._block()

    def _block(self):
        block = {"label": "B%d" % len(self.function["blocks"]), "instructions": []}
        self.function["blocks"].append(block)
        return block

    def _temporary(self, value_type):
        name = "t:%d" % self.next_temporary
        self.next_temporary += 1
        self.function["types"][name] = value_type
        return name

    def _emit(self, op, node, **fields):
        instruction = {"op": op, **fields, "pos": _position(node)}
        self.current["instructions"].append(instruction)
        return instruction

    def _result(self, op, node, value_type, arguments, **fields):
        register = self._temporary(value_type)
        self._emit(op, node, dest=register, args=arguments, **fields)
        return {"var": register}

    def _jump(self, target, node):
        self._emit("jump", node, target=target["label"])

    def _call(self, node):
        # Вычисляем все аргументы слева направо до создания инструкции вызова.
        arguments = [self._value(argument) for argument in node.get("args", [])]
        if node["name"] == "length":
            return [self._result("length", node, "int", arguments)]
        value_types = node["inferred_type"]
        if not isinstance(value_types, list):
            value_types = [value_types]
        registers = [self._temporary(value_type) for value_type in value_types]
        self._emit("call", node, dests=registers, name=node["name"], args=arguments)
        return [{"var": register} for register in registers]

    def _value(self, node):
        kind = node["kind"]
        value_type = node["inferred_type"]
        if kind in {"Int", "Bool"}:
            return self._result("copy", node, value_type, [{"const": node["value"]}])
        if kind == "Name":
            return self._result("copy", node, value_type, [{"var": "v:" + node["name"]}])
        if kind == "Call":
            values = self._call(node)
            if len(values) != 1:
                raise ValueError("Множественный возврат разрешён только в присваивании кортежа")
            return values[0]
        if kind == "Unary":
            argument = self._value(node["operand"])
            return self._result("unary", node, value_type, [argument], operator=node["op"])
        if kind == "Binary":
            if node["op"] in {"and", "or", "->"}:
                return self._boolean_value(node)
            left = self._value(node["left"])
            right = self._value(node["right"])
            return self._result("binary", node, value_type, [left, right], operator=node["op"])
        if kind in {"Index", "ArrayUpdate"}:
            arguments = [self._value(node["base"]), self._value(node["index"])]
            if kind == "ArrayUpdate":
                arguments.append(self._value(node["value"]))
            return self._result("set" if kind == "ArrayUpdate" else "get", node,
                                value_type, arguments)
        raise ValueError("Неподдерживаемое исполняемое выражение: %s" % kind)

    def _boolean_value(self, node):
        """Записать True или False во временный регистр по результату условия."""
        result = self._temporary("bool")
        yes, no, join = self._block(), self._block(), self._block()
        self._condition(node, yes, no)
        self.current = yes
        self._emit("copy", node, dest=result, args=[{"const": True}])
        self._jump(join, node)
        self.current = no
        self._emit("copy", node, dest=result, args=[{"const": False}])
        self._jump(join, node)
        self.current = join
        return {"var": result}

    def _condition(self, node, yes, no):
        kind = node["kind"]
        if kind == "Unary" and node["op"] == "not":
            self._condition(node["operand"], no, yes)
            return
        if kind == "Binary" and node["op"] in {"and", "or", "->"}:
            middle = self._block()
            if node["op"] == "and":
                self._condition(node["left"], middle, no)
            elif node["op"] == "or":
                self._condition(node["left"], yes, middle)
            else:
                self._condition(node["left"], middle, yes)
            self.current = middle
            self._condition(node["right"], yes, no)
            return
        condition = self._value(node)
        self._emit("branch", node, args=[condition], **{"then": yes["label"], "else": no["label"]})

    def _statement(self, node):
        if node is None:
            return
        kind = node["kind"]
        if kind == "Block":
            for statement in node.get("statements", []):
                self._statement(statement)
        elif kind == "Assign":
            value = node["value"]
            values = self._call(value) if value["kind"] == "Call" else [self._value(value)]
            for target, argument in zip(node["targets"], values):
                self._emit("copy", target, dest="v:" + target["name"], args=[argument])
        elif kind == "If":
            yes, no, join = self._block(), self._block(), self._block()
            self._condition(node["condition"], yes, no)
            self.current = yes
            self._statement(node["then"])
            self._jump(join, node)
            self.current = no
            self._statement(node.get("else"))
            self._jump(join, node)
            self.current = join
        elif kind == "While":
            header, body, done = self._block(), self._block(), self._block()
            self._jump(header, node)
            self.current = header
            if node.get("invariant") is not None:
                self.function["contracts"]["invariants"].append({
                    "block": header["label"], "predicate": deepcopy(node["invariant"])})
            self._condition(node["condition"], body, done)
            self.current = body
            self._statement(node["body"])
            self._jump(header, node)
            self.current = done
        elif kind in {"Assert", "Assume"}:
            self._emit("spec", node, kind=kind.lower(),
                       predicate=deepcopy(node["predicate"]), args=[])
        else:
            raise ValueError("Неподдерживаемый исполняемый оператор: %s" % kind)

    def run(self):
        self._statement(self.declaration["body"])
        self._emit("return", self.declaration, args=[
            {"var": "v:" + variable["name"]} for variable in self.function["returns"]])
        return self.function


def lower(ast):
    """Построить новый модуль IR из дерева, в котором уже проверены имена и типы."""
    declarations = ast.get("declarations", [])
    return {"version": 1,
            "functions": [_FunctionLowerer(declaration).run() for declaration in declarations
                          if declaration["kind"] == "Function"],
            "formulas": [deepcopy(declaration) for declaration in declarations
                         if declaration["kind"] == "Formula"]}
