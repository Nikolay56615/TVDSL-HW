"""Модульные тесты алгоритмов. Запуск из корня:  python -m unittest discover -s tests"""

import itertools
import random
import re
import unittest

from funnylex import export, regex
from funnylex.alphabet import SIZE
from funnylex.dfa import DFA, subset_construction
from funnylex.minimize import hopcroft, minimize
from funnylex.nfa import build_nfa, simulate
from funnylex.scanner import Table, tokenize
from funnylex.spec import parse_spec

# Выражения записаны так, чтобы их понимал и модуль re - он служит независимым эталоном.
PATTERNS = ["a|b", "(ab)*", "(a|b)*abb", "a(b|c)d", "abd|acd", "0|[1-9][0-9]*",
            "[a-c_][a-c0-2_]*", "//[^\n]*", "(a*b*)*", "a(b*|c+)?d", "(a|)b"]


def automata(pattern):
    """(НКА, ДКА, минимальный ДКА) для одного выражения."""
    nfa = build_nfa([regex.parse(pattern)])
    dfa, _ = subset_construction(nfa)
    return nfa, dfa, minimize(dfa)


def moore(dfa):
    """Наивная минимизация (итеративное уточнение) - эталон для проверки Хопкрофта.
    Возвращает block_of, как и hopcroft()."""
    ids = {}
    block_of = [ids.setdefault(a, len(ids)) for a in dfa.accept]
    while True:
        ids = {}
        new = [ids.setdefault((block_of[s], tuple(block_of[t] for t in dfa.trans[s])), len(ids))
               for s in range(dfa.n_states)]
        if len(ids) == len(set(block_of)):
            return new
        block_of = new


def make_table(spec_text):
    """tokens.spec в виде строки -> таблица сканера (без записи в файл)."""
    rules = parse_spec(spec_text)
    dfa, _ = subset_construction(build_nfa([r.tree for r in rules]))
    return Table(export.to_dict(minimize(dfa), rules, "test"))


class RegexTests(unittest.TestCase):
    def test_tree(self):
        digit, nonzero = frozenset(range(48, 58)), frozenset(range(49, 58))
        expected = ("alt", ("chars", frozenset([48])), ("cat", ("chars", nonzero), ("star", ("chars", digit))))
        self.assertEqual(regex.parse("0|[1-9][0-9]*"), expected)

    def test_precedence(self):
        # постфиксные операции сильнее конкатенации, конкатенация сильнее |
        a, b = ("chars", frozenset([97])), ("chars", frozenset([98]))
        self.assertEqual(regex.parse("ab*|b"), ("alt", ("cat", a, ("star", b)), b))

    def test_errors(self):
        for bad in ("(a", "a)", "*a", "a|+", "[abc", "[]", "[z-a]", "\\", "\\q"):
            with self.assertRaises(regex.RegexError, msg=bad):
                regex.parse(bad)


class AutomataTests(unittest.TestCase):
    def test_nfa_dfa_min_dfa_agree_with_re(self):
        # все строки длины до 4 над небольшим алфавитом
        for pattern in PATTERNS:
            nfa, dfa, mini = automata(pattern)
            oracle = re.compile(pattern)
            for n in range(5):
                for word in map("".join, itertools.product("abc01_/\n", repeat=n)):
                    expected = oracle.fullmatch(word) is not None
                    self.assertEqual(simulate(nfa, word) is not None, expected, (pattern, word))
                    self.assertEqual(dfa.classify(word) is not None, expected, (pattern, word))
                    self.assertEqual(mini.classify(word) is not None, expected, (pattern, word))

    def test_sizes_for_int(self):
        nfa, dfa, mini = automata("0|[1-9][0-9]*")
        self.assertEqual((nfa.n_states, dfa.n_states, mini.n_states), (11, 5, 4))

    def test_trap_is_the_empty_subset(self):
        nfa = build_nfa([regex.parse("ab")])
        dfa, subsets = subset_construction(nfa)
        self.assertEqual(subsets[dfa.trap()], frozenset())

    def test_priority_of_rules(self):
        # "if" подходит под оба правила - побеждает верхнее; "iff" длиннее - только IDENT
        nfa = build_nfa([regex.parse("if"), regex.parse("[a-z]+")])
        dfa, _ = subset_construction(nfa)
        self.assertEqual([dfa.classify(w) for w in ("if", "iff", "i", "if1")], [0, 1, 1, None])

    def test_textbook_example(self):
        # Хопкрофт, Мотвани, Ульман, рис. 4.8: состояния A..H над {0,1}, принимает только C.
        # Ответ из книги: эквивалентны A~E, B~H, D~F -> 5 состояний (+ наша ловушка = 6).
        table = {"A": "BF", "B": "GC", "C": "AC", "D": "CG", "E": "HF", "F": "CG", "G": "GE", "H": "GC"}
        names = "ABCDEFGH"
        trap = len(names)
        trans = []
        for name in names:
            row = [trap] * SIZE
            row[ord("0")], row[ord("1")] = names.index(table[name][0]), names.index(table[name][1])
            trans.append(row)
        trans.append([trap] * SIZE)
        accept = [0 if name == "C" else None for name in names] + [None]
        dfa = DFA(trans, accept)
        blocks = hopcroft(dfa)
        self.assertEqual(blocks[0], blocks[4])      # A ~ E
        self.assertEqual(blocks[1], blocks[7])      # B ~ H
        self.assertEqual(blocks[3], blocks[5])      # D ~ F
        self.assertEqual(minimize(dfa).n_states, 6)

    def test_hopcroft_agrees_with_moore_on_random_dfas(self):
        rng = random.Random(7)
        for _ in range(200):
            n = rng.randint(1, 9)
            trans = [[rng.randrange(n) for _ in range(SIZE)] for _ in range(n)]
            accept = [rng.choice([None, None, 0, 1]) for _ in range(n)]
            dfa = DFA(trans, accept)
            by_hopcroft, by_moore = hopcroft(dfa), moore(dfa)
            # одинаковое разбиение: состояния лежат в одном блоке у обоих алгоритмов одновременно
            pairs = set(zip(by_hopcroft, by_moore))
            self.assertEqual(len(pairs), len(set(by_hopcroft)))
            self.assertEqual(len(pairs), len(set(by_moore)))

    def test_states_of_different_tokens_are_not_merged(self):
        # состояния "принял a" и "принял b" ведут себя одинаково (дальше только ловушка),
        # но склеивать их нельзя - иначе потеряем, какой токен распознан
        nfa = build_nfa([regex.parse("a"), regex.parse("b")])
        dfa, _ = subset_construction(nfa)
        mini = minimize(dfa)
        self.assertEqual(mini.n_states, 4)          # старт, "a", "b", ловушка
        self.assertEqual((mini.classify("a"), mini.classify("b")), (0, 1))


class ScannerTests(unittest.TestCase):
    SPEC = "\n".join([r"skip WS = [ \t\n]+", "token IF = if", "token IDENT = [a-z]+",
                      "token LT = <", "token LE = <=", "token ASSIGN = ="])

    def test_longest_match_and_priority(self):
        table = make_table(self.SPEC)
        tokens = tokenize(table, "if iff i <== <")
        self.assertEqual([(t.kind, t.lexeme) for t in tokens],
                         [("IF", "if"), ("IDENT", "iff"), ("IDENT", "i"), ("LE", "<="), ("ASSIGN", "="), ("LT", "<")])

    def test_backtracking_to_last_accepting_state(self):
        # после "abc" автомат ещё жив (ждёт "d"), но текст кончается - откат к токену A
        table = make_table("token A = a\ntoken ABCD = abcd\n")
        self.assertEqual([t.kind for t in tokenize(table, "aabcabcd")], ["A", "A", "ERROR", "ABCD"])

    def test_errors_and_positions(self):
        table = make_table(self.SPEC)
        tokens = tokenize(table, "ab = 1;\n  x @@ y")
        self.assertEqual([(t.kind, t.lexeme, t.line, t.col) for t in tokens],
                         [("IDENT", "ab", 1, 1), ("ASSIGN", "=", 1, 4), ("ERROR", "1;", 1, 6),
                          ("IDENT", "x", 2, 3), ("ERROR", "@@", 2, 5), ("IDENT", "y", 2, 8)])


if __name__ == "__main__":
    unittest.main()
