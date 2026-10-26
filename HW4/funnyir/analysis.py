"""Переходы между блоками, живые значения и конфликты регистров."""

from itertools import combinations

from .ir import definitions, successors, uses


def build_cfg(function: dict) -> dict:
    """Найти переходы между блоками и отметить блоки, достижимые от входа."""
    blocks = {block["label"]: block for block in function["blocks"]}
    cfg = {
        label: {
            "successors": sorted(set(successors(blocks[label]))),
            "predecessors": [],
            "reachable": False,
        }
        for label in sorted(blocks)
    }
    for label, node in cfg.items():
        for target in node["successors"]:
            if target not in cfg:
                raise ValueError(f"Неизвестная метка блока: {target}")
            cfg[target]["predecessors"].append(label)
    for node in cfg.values():
        node["predecessors"].sort()

    pending = [function["entry"]]
    while pending:
        label = pending.pop()
        if label not in cfg:
            raise ValueError(f"Неизвестная входная метка: {label}")
        if not cfg[label]["reachable"]:
            cfg[label]["reachable"] = True
            pending.extend(cfg[label]["successors"])
    return cfg


def _block_sets(block: dict) -> tuple[set, set]:
    """Найти чтения до первой записи в регистр и все записи внутри блока."""
    block_use, block_defs = set(), set()
    for instruction in block["instructions"]:
        block_use.update(uses(instruction) - block_defs)
        block_defs.update(definitions(instruction))
    return block_use, block_defs


def analyze(function: dict) -> dict:
    """Рассчитать живость, построить граф конфликтов и назначить цвета.

    Расчёт повторяется, пока множества не перестанут меняться:
    так учитываются обратные переходы в циклах.
    """
    cfg = build_cfg(function)
    blocks = {block["label"]: block for block in function["blocks"]}
    block_use, block_defs = {}, {}
    for label, block in blocks.items():
        block_use[label], block_defs[label] = _block_sets(block)
    live_in = {label: set() for label in cfg}
    live_out = {label: set() for label in cfg}
    changed = True
    while changed:
        changed = False
        for label in reversed(list(cfg)):
            outgoing = set()
            for target in cfg[label]["successors"]:
                outgoing.update(live_in[target])
            incoming = block_use[label] | (outgoing - block_defs[label])
            if outgoing != live_out[label] or incoming != live_in[label]:
                live_out[label], live_in[label] = outgoing, incoming
                changed = True

    # Даже регистр без конфликтов должен получить цвет.
    graph = {f"v:{parameter['name']}": set() for parameter in function["params"]}
    for block in blocks.values():
        for instruction in block["instructions"]:
            for register in uses(instruction) | definitions(instruction):
                graph.setdefault(register, set())

    def connect(left: str, right: str) -> None:
        if left != right:
            graph[left].add(right)
            graph[right].add(left)

    def clique(registers: set) -> None:
        for left, right in combinations(sorted(registers), 2):
            connect(left, right)

    for label, block in blocks.items():
        live = set(live_out[label])
        clique(live)
        for instruction in reversed(block["instructions"]):
            written = definitions(instruction)
            # Все результаты вызова записываются одновременно, поэтому нужны разные места.
            clique(written)
            for destination in written:
                for register in live:
                    connect(destination, register)
            live = uses(instruction) | (live - written)
            # Операнды нужны одновременно, даже если дальше они не используются.
            clique(live)
        clique(live_in[label])

    colors = {}
    for register in sorted(graph, key=lambda item: (-len(graph[item]), item)):
        occupied = {colors[neighbor] for neighbor in graph[register] if neighbor in colors}
        color = 0
        while color in occupied:
            color += 1
        colors[register] = color
    return {
        "cfg": cfg,
        "blocks": {
            label: {
                "use": sorted(block_use[label]),
                "defs": sorted(block_defs[label]),
                "live_in": sorted(live_in[label]),
                "live_out": sorted(live_out[label]),
            }
            for label in cfg
        },
        "interference": {register: sorted(graph[register]) for register in sorted(graph)},
        "colors": {register: colors[register] for register in sorted(colors)},
        "color_count": max(colors.values(), default=-1) + 1,
    }
