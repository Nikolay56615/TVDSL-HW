"""ДКА и конструкция подмножеств (НКА -> ДКА)."""

from collections import deque

from .alphabet import SIZE, symbol
from .nfa import eps_closure, label


class DFA:
    """Полный ДКА: переход определён из каждого состояния по каждому символу.

    trans[s][c] - состояние, в которое ведёт переход из s по символу c;
    accept[s]   - номер правила, если s принимающее, иначе None;
    start       - стартовое состояние.
    """

    def __init__(self, trans, accept, start=0):
        self.trans = trans
        self.accept = accept
        self.start = start

    @property
    def n_states(self):
        return len(self.trans)

    def classify(self, text):
        """Прогоняет ВСЮ строку; возвращает номер правила или None (строка отвергнута)."""
        state = self.start
        for ch in text:
            state = self.trans[state][symbol(ch)]
        return self.accept[state]

    def trap(self):
        """Ловушка: непринимающее состояние, все переходы из которого ведут в него же."""
        for s in range(self.n_states):
            if self.accept[s] is None and all(t == s for t in self.trans[s]):
                return s
        return None


def subset_construction(nfa):
    """Конструкция подмножеств. Возвращает (ДКА, subsets).

    Состояние ДКА = множество состояний НКА, в которых НКА «может быть» одновременно
    после прочитанного текста; subsets[i] - это множество для i-го состояния ДКА.
    Пустое множество - тоже состояние: из него нет выхода, это и есть ловушка.
    """
    start = eps_closure(nfa, [nfa.start])
    subsets = [start]
    index = {start: 0}                       # множество -> номер состояния ДКА
    trans = []
    queue = deque([start])
    while queue:
        current = queue.popleft()
        row = []
        for c in range(SIZE):
            moved = {t for s in current for chars, t in nfa.edges[s] if c in chars}
            target = eps_closure(nfa, moved)
            if target not in index:          # новое множество - новое состояние ДКА
                index[target] = len(subsets)
                subsets.append(target)
                queue.append(target)
            row.append(index[target])
        trans.append(row)
    accept = [label(nfa, subset) for subset in subsets]
    return DFA(trans, accept), subsets
