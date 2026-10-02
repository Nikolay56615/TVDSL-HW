"""Публичный API: parse(text) -> ParseResult; AST состоит из JSON-объектов."""

from .parser import Diagnostic, ParseResult, parse_tokens
from .lexer import lex


def parse(text, table_path=None):
    """Разобрать текст, сохранив частичный AST и диагностику всех этапов."""
    tokens, lexical = lex(text, table_path)
    result = parse_tokens(tokens)
    result.diagnostics = sorted(lexical + result.diagnostics,
                                key=lambda d: (d.line, d.col, d.phase))
    return result


__all__ = ["parse", "parse_tokens", "lex", "Diagnostic", "ParseResult"]
