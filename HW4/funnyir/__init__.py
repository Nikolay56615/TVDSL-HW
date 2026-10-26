"""Funny -> типизированный AST HW3 -> IR, оптимизации и анализ живости."""

from copy import deepcopy
from dataclasses import dataclass

from HW3.funnytypes import check, check_ast
from .interpreter import IRRuntimeError, execute


@dataclass
class CompilationResult:
    before: object
    after: object
    diagnostics: list
    analysis_before: dict
    analysis_after: dict
    metrics: dict

    @property
    def ok(self):
        return not self.diagnostics

    def to_dict(self):
        return {"ok": self.ok, "before": self.before, "after": self.after,
                "diagnostics": [error.to_dict() for error in self.diagnostics],
                "analysis_before": self.analysis_before, "analysis_after": self.analysis_after,
                "metrics": self.metrics}


def _metrics(module, analyses):
    from .ir import definitions, uses
    instructions = temporaries = blocks = 0
    for function in module["functions"]:
        referenced = set()
        blocks += len(function["blocks"])
        for block in function["blocks"]:
            instructions += len(block["instructions"])
            for instruction in block["instructions"]:
                referenced.update(definitions(instruction) | uses(instruction))
        temporaries += sum(register.startswith("t:") for register in referenced)
    return {"instructions": instructions, "temporaries": temporaries, "blocks": blocks,
            "colors": max((value["color_count"] for value in analyses.values()), default=0)}


def _compile(checked, optimize, constants, simplify, cse, dce):
    if not checked.ok:
        return CompilationResult(None, None, list(checked.diagnostics), {}, {}, {})
    from .analysis import analyze
    from .lower import lower
    from .optimize import optimize_module
    before = lower(checked.ast)
    after = (optimize_module(before, constants=constants, simplify=simplify, cse=cse, dce=dce)
             if optimize else deepcopy(before))
    analysis_before = {function["name"]: analyze(function) for function in before["functions"]}
    analysis_after = {function["name"]: analyze(function) for function in after["functions"]}
    old, new = _metrics(before, analysis_before), _metrics(after, analysis_after)
    metrics = {"before": old, "after": new,
               "instructions_removed": old["instructions"] - new["instructions"],
               "temporaries_removed": old["temporaries"] - new["temporaries"]}
    return CompilationResult(before, after, [], analysis_before, analysis_after, metrics)


def compile_source(source, *, optimize=True, constants=True, simplify=True,
                   cse=True, dce=True, table=None):
    """Исходный текст -> две версии IR и результаты их анализа."""
    return _compile(check(source, table), optimize, constants, simplify, cse, dce)


def compile_ast(ast, *, optimize=True, constants=True, simplify=True, cse=True, dce=True):
    """Проверить копию AST HW3 и получить IR, не меняя переданное дерево."""
    return _compile(check_ast(ast), optimize, constants, simplify, cse, dce)


__all__ = ["compile_source", "compile_ast", "CompilationResult", "execute", "IRRuntimeError"]
