"""Табличный лексер Funny: токены с позициями, ошибки и конец ввода."""

from pathlib import Path

from HW1.funnylex.alphabet import OTHER
from HW1.funnylex.scanner import Table, Token, tokenize

from .parser import Diagnostic


DEFAULT_TABLE = Path(__file__).resolve().parents[2] / "HW1" / "generated" / "dfa.min.json"


class FunnyTable(Table):
    """ДКА HW1; символ → распознаётся теми же состояниями, что и два символа ->."""

    def __init__(self, data):
        super().__init__(data)
        self.comment_rules = {i for i, rule in enumerate(self.rules)
                              if rule["name"] == "COMMENT" and rule["kind"] == "skip"}

    def step(self, state, ch):
        if ch == "→" and self.accept[state] not in self.comment_rules:
            # Проходим '-' и '>' за один прочитанный символ. Заменять текст нельзя:
            # в true→false слово false начинается в столбце 6, а в true->false — в 7.
            return super().step(super().step(state, "-"), ">")
        return super().step(state, ch)


def load_table(path=None):
    """Загрузить ДКА. В COMMENT символ OTHER читается как обычная буква."""
    table = FunnyTable.load(DEFAULT_TABLE if path is None else path)
    for state, rule in enumerate(table.accept):
        if rule in table.comment_rules:
            table.trans[state][OTHER] = table.trans[state][ord("a")]
    return table


def lex(text, table_path=None):
    """Текст -> (токены с EOF, ошибки). Строки и столбцы считаются с 1."""
    # В сканере HW1 новую строку начинает только LF; CRLF и CR приводим к нему.
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
    # EOF стоит после последнего символа, в том числе на пустой строке после LF.
    tokens.append(Token("EOF", "", len(lines), len(lines[-1]) + 1, "token"))
    return tokens, diagnostics
