"""Разбор регулярного выражения в дерево.

Дерево - вложенные кортежи:
    ("eps",)               пустая строка
    ("chars", {коды})      один символ из набора (набор - frozenset кодов ASCII)
    ("cat", a, b)          сначала a, потом b
    ("alt", a, b)          a или b
    ("star", a)            a повторяется 0 и более раз
    ("plus", a)            1 и более раз
    ("opt", a)             0 или 1 раз

Поддерживается: |  *  +  ?  ( )  [abc]  [a-z0-9]  [^...]  .  и экранирование
\\n \\t \\r, а также \\+ \\( \\[ \\| ... (экранированный знак = он сам).
Отрицание [^...] и точка берутся относительно ASCII.
"""

ASCII = frozenset(range(128))
ESCAPES = {"n": 10, "t": 9, "r": 13}


class RegexError(ValueError):
    pass


class Parser:
    """Рекурсивный спуск. Уровни от слабой операции к сильной: alt -> cat -> repeat -> atom."""

    def __init__(self, text):
        self.text = text
        self.pos = 0

    def peek(self):
        return self.text[self.pos] if self.pos < len(self.text) else None

    def take(self):
        ch = self.text[self.pos]
        self.pos += 1
        return ch

    def error(self, message):
        raise RegexError("%s (позиция %d в /%s/)" % (message, self.pos, self.text))

    def parse(self):
        tree = self.alt()
        if self.peek() is not None:          # остановились не на конце - значит, лишняя ')'
            self.error("лишняя ')'")
        return tree

    def alt(self):
        """alt = cat { '|' cat }"""
        tree = self.cat()
        while self.peek() == "|":
            self.take()
            tree = ("alt", tree, self.cat())
        return tree

    def cat(self):
        """cat = { repeat }   (пустая последовательность = пустая строка)"""
        tree = None
        while self.peek() not in (None, "|", ")"):
            part = self.repeat()
            tree = part if tree is None else ("cat", tree, part)
        return tree if tree is not None else ("eps",)

    def repeat(self):
        """repeat = atom { '*' | '+' | '?' }"""
        tree = self.atom()
        while self.peek() in ("*", "+", "?"):
            op = self.take()
            tree = ({"*": "star", "+": "plus", "?": "opt"}[op], tree)
        return tree

    def atom(self):
        """atom = '(' alt ')' | '[' класс ']' | '.' | '\\' символ | обычный символ"""
        ch = self.peek()
        if ch is None or ch in "*+?":
            self.error("ожидался символ")
        self.take()
        if ch == "(":
            tree = self.alt()
            if self.peek() != ")":
                self.error("нет закрывающей ')'")
            self.take()
            return tree
        if ch == "[":
            return ("chars", self.char_class())
        if ch == ".":
            return ("chars", ASCII - {10})   # любой символ, кроме перевода строки
        if ch == "\\":
            return ("chars", frozenset([self.escape()]))
        return ("chars", frozenset([self.code(ch)]))

    def code(self, ch):
        if ord(ch) > 127:
            self.error("не-ASCII символ в выражении")
        return ord(ch)

    def escape(self):
        """Символ после обратной косой черты: \\n \\t \\r или экранированный знак."""
        if self.peek() is None:
            self.error("выражение кончается на '\\'")
        ch = self.take()
        if ch in ESCAPES:
            return ESCAPES[ch]
        if ch.isalnum():
            self.error("неизвестная последовательность \\" + ch)
        return self.code(ch)

    def class_item(self):
        ch = self.take()
        return self.escape() if ch == "\\" else self.code(ch)

    def char_class(self):
        """Класс символов [abc], [a-z0-9_], [^\\r\\n]. Возвращает набор кодов."""
        negate = self.peek() == "^"
        if negate:
            self.take()
        symbols = set()
        while self.peek() != "]":
            if self.peek() is None:
                self.error("нет закрывающей ']'")
            low = self.class_item()
            # 'a-z' - диапазон; '-' в начале или перед ']' - обычный символ
            if self.peek() == "-" and self.text[self.pos + 1:self.pos + 2] not in ("", "]"):
                self.take()
                high = self.class_item()
                if low > high:
                    self.error("неверный диапазон в [...]")
                symbols.update(range(low, high + 1))
            else:
                symbols.add(low)
        self.take()
        if not symbols:
            self.error("пустой класс [...]")
        return frozenset(ASCII - symbols) if negate else frozenset(symbols)


def parse(text):
    """Текст регулярного выражения -> дерево."""
    return Parser(text).parse()
