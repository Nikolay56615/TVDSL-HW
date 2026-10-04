"""Рекурсивный спуск: поток Token -> дерево программы Funny.

Узлы дерева - словари: kind - вид узла, pos - строка и столбец токена,
остальные поля зависят от kind. У Binary это op, left и right.

По открывающей '(' ещё нельзя отличить (a + b) от (a < b). Поэтому скобки
разбираем одинаково, а затем проверяем, какое выражение получилось.
"""

from dataclasses import dataclass

from HW1.funnylex.scanner import Token


@dataclass
class Diagnostic:
    phase: str
    line: int
    col: int
    message: str

    def to_dict(self):
        return {"phase": self.phase, "line": self.line, "col": self.col,
                "message": self.message}


@dataclass
class ParseResult:
    ast: dict
    diagnostics: list

    @property
    def ok(self):
        return not self.diagnostics

    def to_dict(self):
        return {"ok": self.ok, "ast": self.ast,
                "diagnostics": [error.to_dict() for error in self.diagnostics]}


class _ParseError(Exception):
    """Прерывает разбор; сообщение уже добавлено в diagnostics."""


_COMPARISONS = {"==", "!=", "<", "<=", ">", ">="}
_ARITHMETIC = {"+", "-", "*", "/"}
_STATEMENT_WORDS = {"{", "if", "while", "assert", "assume"}


def _node(kind, token, **fields):
    return {"kind": kind, "pos": {"line": token.line, "col": token.col}, **fields}


def _category(expression):
    """Вид выражения по дереву: arithmetic, boolean или call."""
    kind = expression["kind"]
    if kind in {"Bool", "Quantifier"}:
        return "boolean"
    if kind == "Binary":
        return "arithmetic" if expression["op"] in _ARITHMETIC else "boolean"
    if kind == "Unary":
        return "arithmetic" if expression["op"] == "-" else "boolean"
    if kind == "Call":
        # length(a) - арифметика. f(x) пока может быть и функцией, и формулой:
        # по одному вызову неизвестно, как объявлено f.
        return "arithmetic" if expression["name"] == "length" else "call"
    return "arithmetic"


class _Parser:
    """tokens - поток с EOF в конце; index - номер текущего токена."""

    def __init__(self, tokens):
        raw = list(tokens)
        # Ошибки лексера уже записаны в lexer.py; пробелы и ошибки пропускаем.
        self.tokens = [token for token in raw
                       if token.category not in {"skip", "error"}
                       and token.kind != "ERROR"]
        eof = next((i for i, token in enumerate(self.tokens) if token.kind == "EOF"), None)
        if eof is not None:
            self.tokens = self.tokens[:eof + 1]
        else:
            line, col = 1, 1
            if raw:
                last = raw[-1]
                parts = last.lexeme.replace("\r\n", "\n").replace("\r", "\n").split("\n")
                line = last.line + len(parts) - 1
                col = last.col + len(parts[0]) if len(parts) == 1 else len(parts[-1]) + 1
            self.tokens.append(Token("EOF", "", line, col, "token"))
        self.index = 0
        self.diagnostics = []

    @property
    def token(self):
        return self.tokens[self.index]

    def _text(self, offset=0):
        token = self.tokens[min(self.index + offset, len(self.tokens) - 1)]
        if token.kind == "EOF":
            return "<EOF>"  # Не спутать конец файла с переменной по имени EOF.
        return "->" if token.kind == "ARROW" else token.lexeme

    def _advance(self):
        token = self.token
        if token.kind != "EOF":
            self.index += 1
        return token

    def _match(self, text):
        if self._text() == text:
            return self._advance()
        return None

    def _diagnose(self, message, token=None):
        token = self.token if token is None else token
        self.diagnostics.append(Diagnostic("syntax", token.line, token.col, message))

    def _fail(self, message, token=None):
        self._diagnose(message, token)
        raise _ParseError(message)

    def _expect(self, text):
        token = self._match(text)
        if token is None:
            found = "конец файла" if self._text() == "<EOF>" else repr(self.token.lexeme)
            self._fail("Ожидалось %r, получено %s" % (text, found))
        return token

    def _identifier(self):
        if self.token.kind != "IDENT":
            self._fail("Ожидался идентификатор")
        return self._advance()

    def _declaration_start(self):
        """Начинается ли здесь следующее объявление? Токены не забираем.

        После f(...) ищем returns, requires или =>: вызов f(...); сюда не подходит.
        Так можно сохранить следующее объявление, даже если перед ним забыли '}'.
        """
        if self._text() == "function":
            return True
        if self.token.kind != "IDENT" or self._text(1) != "(":
            return False
        depth = 0                       # число незакрытых скобок в заголовке
        for position in range(self.index + 1, len(self.tokens)):
            text = self.tokens[position].lexeme
            if text == "(":
                depth += 1
            elif text == ")":
                depth -= 1
                if depth == 0:
                    following = self.tokens[min(position + 1, len(self.tokens) - 1)].lexeme
                    return following in {"returns", "requires", "=>"}
            elif text in {";", "{", "}"} or self.tokens[position].kind == "EOF":
                return False
        return False

    def _statement_start(self):
        return self._text() in _STATEMENT_WORDS or self.token.kind == "IDENT"

    def _sync_declaration(self, start):
        """Пропустить ошибочное объявление до следующего заголовка."""
        # Если ошибка на первом токене, сдвигаемся сами, иначе разберём его снова.
        if self.index == start and self._text() != "<EOF>":
            self._advance()
        while self._text() != "<EOF>" and not self._declaration_start():
            self._advance()

    def _sync_statement(self, start):
        """Пропустить остаток оператора; start - где начался его разбор."""
        while self._text() != "<EOF>":
            if self._text() == ";":
                self._advance()
                return
            if self._text() in {"}", "else"} or self._declaration_start():
                return
            # Новое присваивание или if сохраняем, но только после сдвига:
            # тот же ошибочный токен иначе будет разбираться бесконечно.
            if self.index > start and self._statement_start():
                return
            self._advance()

    def parse(self):
        declarations = []
        if self._text() == "<EOF>":
            self._diagnose("Модуль пуст: ожидалось объявление функции или формулы")
        while self._text() != "<EOF>":
            start = self.index
            try:
                declarations.append(self._declaration())
            except _ParseError:
                self._sync_declaration(start)
            except RecursionError:
                self._diagnose("Слишком глубокая вложенность программы")
                self._sync_declaration(start)
        return ParseResult({"kind": "Module", "pos": {"line": 1, "col": 1},
                            "declarations": declarations}, self.diagnostics)

    def _variable(self, required_type=True):
        name = self._identifier()
        variable_type = None
        if required_type:
            self._expect(":")
            variable_type = self._type()
        elif self._match(":"):
            variable_type = self._type()
        return _node("VariableDecl", name, name=name.lexeme, type=variable_type)

    def _type(self):
        self._expect("int")
        if self._match("["):
            self._expect("]")
            return "int[]"
        return "int"

    def _variables(self, required_type=True):
        variables = [self._variable(required_type)]
        while self._match(","):
            variables.append(self._variable(required_type))
        return variables

    def _declaration(self):
        keyword = self._match("function")
        name = self._identifier()
        position = name if keyword is None else keyword
        self._expect("(")
        params = [] if self._text() == ")" else self._variables()
        self._expect(")")
        if self._match("=>"):
            if keyword is not None:
                self._fail("После 'function' ожидалось объявление функции, а не формулы", keyword)
            predicate = self._predicate()
            # В грамматике после формулы нет ';', но в примерах она встречается.
            self._match(";")
            return _node("Formula", position, name=name.lexeme, params=params,
                         predicate=predicate)

        requires = _node("Bool", position, value=True)
        has_requires = self._match("requires")
        if has_requires:
            requires = self._predicate()
        self._expect("returns")
        returns = self._variables()
        # В примерах курса requires бывает и после returns.
        late_requires = self._match("requires")
        if late_requires:
            if has_requires:
                self._diagnose("Повторное предусловие 'requires'", late_requires)
            requires = self._predicate()
        ensures = self._predicate() if self._match("ensures") else _node("Bool", position, value=False)
        locals_ = self._variables(False) if self._match("uses") else []
        body = self._recovered_statement()
        return _node("Function", position, name=name.lexeme, params=params, returns=returns,
                     requires=requires, ensures=ensures, locals=locals_, body=body)

    def _recovered_statement(self):
        start, position = self.index, self.token
        try:
            return self._statement()
        except _ParseError as error:
            self._sync_statement(start)
            return _node("Error", position, message=str(error))

    def _statement(self):
        text = self._text()
        if text == "{":
            return self._block()
        if text == "if":
            return self._if()
        if text == "while":
            return self._while()
        if text in {"assert", "assume"}:
            keyword = self._advance()
            predicate = self._predicate()
            self._expect(";")
            return _node("Assert" if text == "assert" else "Assume", keyword, predicate=predicate)
        if self.token.kind == "IDENT" and not self._declaration_start():
            return self._assignment()
        self._fail("Ожидался оператор присваивания, if, while, блок, assert или assume")

    def _block(self):
        brace = self._expect("{")
        statements = []
        while self._text() not in {"}", "<EOF>"}:
            if self._declaration_start():
                self._diagnose("Ожидалось '}' перед следующим объявлением")
                return _node("Block", brace, statements=statements)
            start = self.index
            statements.append(self._recovered_statement())
            # _sync_statement оставляет else для if. Если здесь нет такого if,
            # забираем else сами, иначе цикл снова наткнётся на него же.
            if self.index == start and self._text() not in {"}", "<EOF>"}:
                self._advance()
        if self._text() == "<EOF>":
            self._diagnose("Ожидалось '}', получен конец файла")
        else:
            self._advance()
        return _node("Block", brace, statements=statements)

    def _if(self):
        keyword = self._expect("if")
        self._expect("(")
        condition = self._condition()
        self._expect(")")
        then = self._recovered_statement()
        # В if (a > 0) if (b > 0) x=1; else x=2; else забирает внутренний _if.
        otherwise = self._recovered_statement() if self._match("else") else None
        return _node("If", keyword, condition=condition, then=then, **{"else": otherwise})

    def _while(self):
        keyword = self._expect("while")
        self._expect("(")
        condition = self._condition()
        self._expect(")")
        invariant = self._predicate() if self._match("invariant") else _node("Bool", keyword, value=True)
        body = self._recovered_statement()
        return _node("While", keyword, condition=condition, invariant=invariant, body=body)

    def _assignment(self):
        name = self._identifier()
        target = _node("Name", name, name=name.lexeme)
        indexes = []
        while self._text() == "[":
            bracket = self._advance()
            index = self._arithmetic()
            self._expect("]")
            indexes.append((bracket, index))
        targets = [target]
        while self._match(","):
            if indexes:
                self._fail("Элемент массива недопустим в левой части присваивания кортежа")
            other = self._identifier()
            targets.append(_node("Name", other, name=other.lexeme))
            if self._text() == "[":
                self._fail("Элемент массива недопустим в левой части присваивания кортежа")
        self._expect("=")
        value = self._arithmetic()
        if len(targets) > 1 and value["kind"] != "Call":
            self._diagnose("Присваивание кортежа требует вызова функции справа", name)
        self._expect(";")
        if indexes:
            # a[i][j] = v -> a = set(a, i, set(a[i], j, v)).
            # bases - массив перед каждым индексом: [a, a[i]] для примера выше.
            # Эти же узлы ставим в ArrayUpdate: сначала обновляем a[i], затем a.
            bases, base = [], target
            for bracket, index in indexes:
                bases.append(base)
                base = _node("Index", bracket, base=base, index=index)
            for (bracket, index), base in reversed(list(zip(indexes, bases))):
                value = _node("ArrayUpdate", bracket, base=base, index=index, value=value)
        return _node("Assign", name, targets=targets, value=value)

    def _require_arithmetic(self, expression):
        if _category(expression) == "boolean":
            pos = expression["pos"]
            self.diagnostics.append(Diagnostic("syntax", pos["line"], pos["col"],
                                               "Ожидалось арифметическое выражение, получен предикат"))

    def _require_boolean(self, expression, predicate):
        category = _category(expression)
        # В предикате f(x) может быть ссылкой на формулу. В if/while нужен
        # boolean: сравнение, логическая операция или true/false.
        if category == "boolean" or (predicate and category == "call"):
            return
        pos = expression["pos"]
        message = "Ожидался предикат" if predicate else "Ожидалось логическое условие"
        if category == "call" and not predicate:
            message += "; ссылка на формулу разрешена только в предикатах"
        self.diagnostics.append(Diagnostic("syntax", pos["line"], pos["col"], message))

    def _arithmetic(self):
        value = self._expression(False)
        self._require_arithmetic(value)
        return value

    def _predicate(self):
        value = self._expression(True)
        self._require_boolean(value, True)
        return value

    def _condition(self):
        value = self._expression(False)
        self._require_boolean(value, False)
        return value

    def _expression(self, predicate):
        """Уровни от слабой операции к сильной:
        импликация, or, and, not, сравнение, + и -, * и /, унарный -.
        Скобки начинают разбор заново с импликации.

        predicate=True разрешает ссылки на формулы и кванторы.
        """
        # Справа вызываем тот же уровень: p -> q -> r = p -> (q -> r).
        left = self._or(predicate)
        operator = self._match("->")
        if operator:
            right = self._expression(predicate)
            self._require_boolean(left, predicate)
            self._require_boolean(right, predicate)
            return _node("Binary", operator, op="->", left=left, right=right)
        return left

    def _or(self, predicate):
        left = self._and(predicate)
        while self._text() == "or":
            operator = self._advance()
            right = self._and(predicate)
            self._require_boolean(left, predicate)
            self._require_boolean(right, predicate)
            left = _node("Binary", operator, op="or", left=left, right=right)
        return left

    def _and(self, predicate):
        left = self._not(predicate)
        while self._text() == "and":
            operator = self._advance()
            right = self._not(predicate)
            self._require_boolean(left, predicate)
            self._require_boolean(right, predicate)
            left = _node("Binary", operator, op="and", left=left, right=right)
        return left

    def _not(self, predicate):
        operator = self._match("not")
        if operator:
            operand = self._not(predicate)
            self._require_boolean(operand, predicate)
            return _node("Unary", operator, op="not", operand=operand)
        return self._comparison(predicate)

    def _comparison(self, predicate):
        left = self._add(predicate)
        if self._text() in _COMPARISONS:
            operator = self._advance()
            right = self._add(predicate)
            self._require_arithmetic(left)
            self._require_arithmetic(right)
            left = _node("Binary", operator, op=operator.lexeme, left=left, right=right)
            if self._text() in _COMPARISONS:
                self._fail("Цепочки сравнений недопустимы; используйте 'and'")
        return left

    def _add(self, predicate):
        # Слагаемое разбирается целиком: 1 + 2 * 3 = 1 + (2 * 3).
        left = self._multiply(predicate)
        while self._text() in {"+", "-"}:
            operator = self._advance()
            right = self._multiply(predicate)
            self._require_arithmetic(left)
            self._require_arithmetic(right)
            # Новое дерево оборачивает left: 10 - 3 - 2 = (10 - 3) - 2.
            left = _node("Binary", operator, op=operator.lexeme, left=left, right=right)
        return left

    def _multiply(self, predicate):
        left = self._unary(predicate)
        while self._text() in {"*", "/"}:
            operator = self._advance()
            right = self._unary(predicate)
            self._require_arithmetic(left)
            self._require_arithmetic(right)
            left = _node("Binary", operator, op=operator.lexeme, left=left, right=right)
        return left

    def _unary(self, predicate):
        operator = self._match("-")
        if operator:
            operand = self._unary(predicate)
            self._require_arithmetic(operand)
            return _node("Unary", operator, op="-", operand=operand)
        return self._primary(predicate)

    def _primary(self, predicate):
        token, text = self.token, self._text()
        if self._match("("):
            expression = self._expression(predicate)
            self._expect(")")
            return expression
        if text in {"forall", "exists"}:
            return self._quantifier(predicate)
        if text in {"true", "false"}:
            self._advance()
            return _node("Bool", token, value=text == "true")
        if token.kind == "INT":
            self._advance()
            try:
                value = int(token.lexeme)
            except ValueError:
                self._fail("Некорректное или слишком длинное целое число", token)
            return _node("Int", token, value=value)
        if token.kind == "IDENT" or text == "length":
            self._advance()
            if self._match("("):
                args = []
                if self._text() != ")":
                    args.append(self._arithmetic())
                    while self._match(","):
                        args.append(self._arithmetic())
                self._expect(")")
                return _node("Call", token, name=token.lexeme, args=args)
            if text == "length":
                self._fail("После 'length' ожидалось '(' для вызова функции")
            expression = _node("Name", token, name=token.lexeme)
            while self._text() == "[":
                bracket = self._advance()
                index = self._arithmetic()
                self._expect("]")
                expression = _node("Index", bracket, base=expression, index=index)
            return expression
        self._fail("Ожидалось выражение, получено %r" % token.lexeme)

    def _quantifier(self, predicate):
        keyword = self._advance()
        if not predicate:
            self._diagnose("Кванторы разрешены только в предикатах", keyword)
        self._expect("(")
        variable = self._variable()
        self._expect("|")
        body = self._predicate()
        self._expect(")")
        return _node("Quantifier", keyword, quantifier=keyword.lexeme,
                     variable=variable, predicate=body)


def parse_tokens(tokens):
    """Поток Token -> ParseResult (дерево и список синтаксических ошибок).

    EOF добавляется, если его нет в потоке. После ошибки разбираем дальше;
    вместо неразобранного оператора в дереве остаётся узел Error.
    """
    return _Parser(tokens).parse()
