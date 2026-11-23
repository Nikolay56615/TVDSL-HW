from HW2.funnyparse import parse
from .checker import CheckResult, Diagnostic, check_ast


def check(source, table=None, *, implicit_locals=False):
    """Сначала HW2, затем HW3"""
    parsed = parse(source, table)
    result = check_ast(parsed.ast, implicit_locals=implicit_locals)
    result.diagnostics = list(parsed.diagnostics) + result.diagnostics
    return result


__all__ = ["check", "check_ast", "CheckResult", "Diagnostic"]
