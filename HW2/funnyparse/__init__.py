"""Разбор текста Funny: токены HW1 -> AST и список ошибок."""

from .parser import Diagnostic, ParseResult, parse_tokens
from .lexer import lex


def parse(text, table_path=None):
    """Текст -> ParseResult: дерево ast, список diagnostics и признак ok.

    Лексические ошибки собирает lex(), синтаксические — parse_tokens().
    Оба списка нужны: парсер пропускает ошибочные лексемы, но из-за этого
    исходная программа не становится правильной.
    """
    tokens, lexical = lex(text, table_path)
    result = parse_tokens(tokens)
    result.diagnostics = sorted(lexical + result.diagnostics,
                                key=lambda d: (d.line, d.col, d.phase))
    return result


__all__ = ["parse", "parse_tokens", "lex", "Diagnostic", "ParseResult"]
