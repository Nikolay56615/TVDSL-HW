"""Запись автомата в файлы: JSON (для программ), CSV (для чтения глазами), DOT (картинка)."""

import json

from .alphabet import OTHER

NAMES = {9: "\\t", 10: "\\n", 13: "\\r", 32: "SP", OTHER: "OTHER"}


def symbol_name(c):
    """Печатное имя символа: 'a', 'SP', '\\n', 'x7F'."""
    if c in NAMES:
        return NAMES[c]
    return chr(c) if 33 <= c <= 126 else "x%02X" % c


def symbols_label(codes):
    """Компактная запись набора символов: [65..90, 95, 97..122] -> 'A-Z _ a-z'."""
    codes = sorted(codes)
    parts, i = [], 0
    while i < len(codes):
        j = i
        while j + 1 < len(codes) and codes[j + 1] == codes[j] + 1 and codes[j + 1] < OTHER:
            j += 1
        if j - i >= 2:                       # три и более подряд - записываем диапазоном
            parts.append(symbol_name(codes[i]) + "-" + symbol_name(codes[j]))
        else:
            parts.extend(symbol_name(c) for c in codes[i:j + 1])
        i = j + 1
    return " ".join(parts)


def grouped_edges(dfa, state):
    """Переходы состояния, сгруппированные по цели: {цель: [символы]}."""
    groups = {}
    for c, target in enumerate(dfa.trans[state]):
        groups.setdefault(target, []).append(c)
    return groups


def to_dict(dfa, rules, source):
    """Всё описание ДКА одним словарём - его достаточно, чтобы написать сканер."""
    return {
        "source": source,
        "alphabet": "symbol = ASCII code 0..127; symbol 128 = any non-ASCII character",
        "rules": [{"name": r.name, "kind": r.kind, "regex": r.pattern} for r in rules],
        "n_states": dfa.n_states,
        "start": dfa.start,
        "trap": dfa.trap(),
        "accept": dfa.accept,
        "transitions": dfa.trans,
    }


def to_json(data):
    """JSON, в котором каждая строка таблицы переходов занимает одну строку файла."""
    lines = ["{"]
    for key in ("source", "alphabet", "n_states", "start", "trap"):
        lines.append('  "%s": %s,' % (key, json.dumps(data[key])))
    lines.append('  "rules": [')
    lines.append(",\n".join("    " + json.dumps(rule) for rule in data["rules"]))
    lines.append("  ],")
    lines.append('  "accept": %s,' % json.dumps(data["accept"]))
    lines.append('  "transitions": [')
    lines.append(",\n".join("    " + json.dumps(row) for row in data["transitions"]))
    lines.append("  ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def to_csv(dfa, rules):
    """Список переходов без ловушки: state,token,kind,symbols,next (одна строка на группу символов)."""
    trap = dfa.trap()
    lines = ["state,token,kind,symbols,next"]
    for s in range(dfa.n_states):
        rule = rules[dfa.accept[s]] if dfa.accept[s] is not None else None
        token = rule.name if rule else ("TRAP" if s == trap else "")
        kind = rule.kind if rule else ""
        edges = [(t, codes) for t, codes in grouped_edges(dfa, s).items() if t != trap]
        if not edges:                        # состояние, из которого дальше только ловушка
            lines.append("%d,%s,%s,," % (s, token, kind))
        for t, codes in edges:
            lines.append('%d,%s,%s,"%s",%d' % (s, token, kind, symbols_label(codes).replace('"', '""'), t))
    return "\n".join(lines) + "\n"


def to_dot(dfa, rules):
    """Граф для Graphviz (dot -Tsvg). Ловушка и переходы в неё не рисуются - иначе не разглядеть."""
    trap = dfa.trap()
    lines = ["digraph dfa {", "  rankdir=LR;", "  node [shape=circle];",
             "  start [shape=point];", "  start -> %d;" % dfa.start]
    for s in range(dfa.n_states):
        if s == trap:
            continue
        if dfa.accept[s] is not None:
            lines.append('  %d [shape=doublecircle, label="%d\\n%s"];' % (s, s, rules[dfa.accept[s]].name))
        for t, codes in grouped_edges(dfa, s).items():
            if t != trap:
                text = symbols_label(codes).replace("\\", "\\\\").replace('"', '\\"')
                lines.append('  %d -> %d [label="%s"];' % (s, t, text))
    lines.append("}")
    return "\n".join(lines) + "\n"
