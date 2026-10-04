"""Минимизация ДКА алгоритмом Хопкрофта."""

from collections import deque

from .alphabet import SIZE
from .dfa import DFA


def hopcroft(dfa):
    """Разбивает состояния на блоки неразличимых. Возвращает block_of[s] - номер блока.

    Начальное разбиение - по метке: какой токен принимает состояние (а не просто
    «принимающие / непринимающие», иначе состояния разных токенов склеились бы).
    Дальше блок раскалывается, если часть его состояний по символу c ведёт
    в блок-разделитель, а часть - нет. В очередь разделителей кладём меньшую
    из половинок - за счёт этого алгоритм работает за O(k * n * log n).
    """
    n = dfa.n_states
    # обратные переходы: inverse[c][q] - из каких состояний попадают в q по символу c
    inverse = [[[] for _ in range(n)] for _ in range(SIZE)]
    for p in range(n):
        for c in range(SIZE):
            inverse[c][dfa.trans[p][c]].append(p)

    by_label = {}
    for s in range(n):
        by_label.setdefault(dfa.accept[s], set()).add(s)
    blocks = list(by_label.values())
    block_of = [0] * n
    for b, block in enumerate(blocks):
        for s in block:
            block_of[s] = b

    work = list(range(len(blocks)))          # блоки-разделители, которые ещё надо обработать
    in_work = [True] * len(blocks)
    while work:
        a = work.pop()
        in_work[a] = False
        splitter = list(blocks[a])           # копия: сам блок a может расколоться по ходу
        for c in range(SIZE):
            # touched[b] - состояния блока b, которые по c попадают в разделитель
            touched = {}
            for q in splitter:
                for p in inverse[c][q]:
                    touched.setdefault(block_of[p], set()).add(p)
            for b, part in touched.items():
                if len(part) == len(blocks[b]):
                    continue                 # весь блок ведёт в разделитель - раскалывать нечего
                blocks[b] -= part            # блок b распадается на blocks[b] и part
                new = len(blocks)
                blocks.append(part)
                in_work.append(False)
                for s in part:
                    block_of[s] = new
                if in_work[b]:
                    chosen = new             # b уже ждёт в очереди - добавляем вторую половину
                else:
                    chosen = new if len(part) <= len(blocks[b]) else b
                work.append(chosen)
                in_work[chosen] = True
    return block_of


def minimize(dfa):
    """Склеивает состояния каждого блока в одно состояние минимального ДКА.

    Блоки нумеруются обходом в ширину от стартового состояния, поэтому
    результат воспроизводим, а недостижимые состояния (если бы они были) отпали бы сами.
    """
    block_of = hopcroft(dfa)
    number = {block_of[dfa.start]: 0}       # блок -> номер нового состояния
    sample = [dfa.start]                     # по одному представителю на блок
    queue = deque([dfa.start])
    while queue:
        s = queue.popleft()
        for t in dfa.trans[s]:
            if block_of[t] not in number:
                number[block_of[t]] = len(sample)
                sample.append(t)
                queue.append(t)
    trans = [[number[block_of[t]] for t in dfa.trans[s]] for s in sample]
    accept = [dfa.accept[s] for s in sample]
    return DFA(trans, accept)
