"""НКА с ε-переходами и построение Томпсона (дерево выражения -> НКА)."""

from .alphabet import symbol


class NFA:
    """Состояния - числа 0..n-1.

    eps[s]   - список состояний, куда из s можно перейти по ε (не читая символ);
    edges[s] - список пар (набор символов, состояние-цель);
    accept   - словарь {принимающее состояние: номер правила}.
    """

    def __init__(self):
        self.eps = []
        self.edges = []
        self.start = None
        self.accept = {}

    @property
    def n_states(self):
        return len(self.eps)

    def new_state(self):
        self.eps.append([])
        self.edges.append([])
        return len(self.eps) - 1


def thompson(nfa, tree):
    """Строит фрагмент НКА для дерева, возвращает (вход, выход) фрагмента.

    У любого фрагмента ровно один вход и один выход, поэтому фрагменты
    легко соединять друг с другом ε-переходами.
    """
    kind = tree[0]
    if kind == "cat":
        start1, end1 = thompson(nfa, tree[1])
        start2, end2 = thompson(nfa, tree[2])
        nfa.eps[end1].append(start2)             # выход первого -> вход второго
        return start1, end2

    start, end = nfa.new_state(), nfa.new_state()
    if kind == "eps":
        nfa.eps[start].append(end)
    elif kind == "chars":
        nfa.edges[start].append((tree[1], end))
    elif kind == "alt":
        for branch in (tree[1], tree[2]):
            s, e = thompson(nfa, branch)
            nfa.eps[start].append(s)             # развилка на две ветки
            nfa.eps[e].append(end)               # ветки сходятся в общий выход
    else:                                        # star, plus, opt
        s, e = thompson(nfa, tree[1])
        nfa.eps[start].append(s)
        nfa.eps[e].append(end)
        if kind in ("star", "opt"):
            nfa.eps[start].append(end)           # можно пропустить целиком
        if kind in ("star", "plus"):
            nfa.eps[e].append(s)                 # можно повторить ещё раз
    return start, end


def build_nfa(trees):
    """Один НКА на все правила: общий старт с ε-переходами во фрагмент каждого правила.

    Выход фрагмента правила номер i получает метку i - по ней потом видно,
    какой токен распознан.
    """
    nfa = NFA()
    nfa.start = nfa.new_state()
    for i, tree in enumerate(trees):
        s, e = thompson(nfa, tree)
        nfa.eps[nfa.start].append(s)
        nfa.accept[e] = i
    return nfa


def eps_closure(nfa, states):
    """ε-замыкание: всё, куда можно дойти из states по одним ε-переходам (включая сами states)."""
    result = set(states)
    stack = list(states)
    while stack:
        for t in nfa.eps[stack.pop()]:
            if t not in result:
                result.add(t)
                stack.append(t)
    return frozenset(result)


def label(nfa, states):
    """Метка множества состояний: правило с наименьшим номером (оно главнее) или None."""
    labels = [nfa.accept[s] for s in states if s in nfa.accept]
    return min(labels) if labels else None


def simulate(nfa, text):
    """Прямой прогон НКА по строке: номер правила или None. Медленно; нужно только тестам."""
    current = eps_closure(nfa, [nfa.start])
    for ch in text:
        sym = symbol(ch)
        moved = {t for s in current for chars, t in nfa.edges[s] if sym in chars}
        current = eps_closure(nfa, moved)
    return label(nfa, current)
