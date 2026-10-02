"""Адаптер табличного лексера HW1 для парсера: позиции, EOF, диагностика."""

from pathlib import Path

from funnylex.alphabet import OTHER
from funnylex.scanner import Table, Token, tokenize

from .parser import Diagnostic


DEFAULT_TABLE = Path(__file__).resolve().parents[2] / "generated" / "dfa.min.json"


class FunnyTable(Table):
    """Таблица HW1 с односимвольным Unicode-оператором импликации Funny."""

    def __init__(self, data):
        super().__init__(data)
        self.comment_rules = {i for i, rule in enumerate(self.rules)
                              if rule["name"] == "COMMENT" and rule["kind"] == "skip"}

    def step(self, state, ch):
        if ch == "→" and self.accept[state] not in self.comment_rules:
            # Один символ исходника проходит два перехода ДКА для ASCII '->'.
            # Лексема остаётся '→', поэтому столбцы следующих токенов не сдвигаются.
            return super().step(super().step(state, "-"), ">")
        return super().step(state, ch)


def load_table(path=None):
    """Загрузить ДКА HW1; поддержать → и Unicode внутри комментариев.

    В HW1 весь алфавит строго ASCII. В примерах курса комментарии на русском,
    поэтому в принимающих состояниях COMMENT символ OTHER ведёт туда же,
    куда обычная буква. Unicode-стрелка — отдельный оператор Funny;
    идентификаторы и прочие символы кода сохраняют алфавит HW1.
    Файл автомата и исходный сканер при этом не изменяются.
    """
    table = FunnyTable.load(DEFAULT_TABLE if path is None else path)
    for state, rule in enumerate(table.accept):
        if rule in table.comment_rules:
            table.trans[state][OTHER] = table.trans[state][ord("a")]
    return table


def lex(text, table_path=None):
    """Вернуть токены с EOF и лексические ошибки. Строки/столбцы с единицы."""
    # Одинаковые позиции для LF, CRLF и старого Mac CR, включая строку EOF.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    tokens = tokenize(load_table(table_path), text)
    diagnostics = []
    for token in tokens:
        if token.category != "error":
            continue
        if token.kind == "BAD_INT":
            message = "Целое число с ведущим нулём: %s" % token.lexeme
        else:
            message = "Недопустимые символы: %r" % token.lexeme
        diagnostics.append(Diagnostic("lexical", token.line, token.col, message))
    lines = text.split("\n")
    tokens.append(Token("EOF", "", len(lines), len(lines[-1]) + 1, "token"))
    return tokens, diagnostics
