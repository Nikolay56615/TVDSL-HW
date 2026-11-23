"""Перевод типизированного IR из HW4 в JVM .class."""

from HW4.funnyir import compile_source as compile_ir

from .backend import emit_class


def compile_source(source, *, optimize=True):
    """Проверить исходник проекта и построить IR с выводом локальных переменных."""
    return compile_ir(source, optimize=optimize, implicit_locals=True)


__all__ = ["compile_source", "emit_class"]
