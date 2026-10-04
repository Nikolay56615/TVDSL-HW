"""Сканер: режет текст на токены по таблице ДКА из JSON.

Модуль читает ТОЛЬКО таблицу (HW1/generated/dfa.min.json) и ничего не знает о том,
как она построена. Ровно так же таблицу подключит лексер проекта.
"""

import json
from collections import namedtuple

# kind - имя правила (IDENT, INT, ...) или ERROR; category - token / skip / error
Token = namedtuple("Token", "kind lexeme line col category")


class Table:
    """Таблица переходов ДКА, загруженная из JSON."""

    def __init__(self, data):
        self.rules = data["rules"]
        self.start = data["start"]
        self.trap = data["trap"]
        self.accept = data["accept"]
        self.trans = data["transitions"]

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def step(self, state, ch):
        """Один шаг автомата. Символы с кодом >= 128 превращаются в символ 128 (OTHER)."""
        code = ord(ch)
        return self.trans[state][code if code < 128 else 128]


def classify(table, text):
    """Имя правила, если ВСЯ строка - один токен, иначе None."""
    state = table.start
    for ch in text:
        state = table.step(state, ch)
    rule = table.accept[state]
    return None if rule is None else table.rules[rule]["name"]


def tokenize(table, text, keep_skipped=False):
    """Разбивает текст на токены по правилу самого длинного совпадения.

    От текущей позиции идём по автомату, пока не попадём в ловушку (или текст
    не кончится), и запоминаем ПОСЛЕДНЕЕ принимающее состояние - там токен
    и заканчивается. Если принимающих состояний не встретилось, символ в начале
    ошибочный: выдаём токен ERROR (соседние ошибочные символы склеиваются в один)
    и продолжаем со следующего символа.
    """
    tokens = []
    line, col = 1, 1
    i, error_end = 0, -1
    while i < len(text):
        state, j = table.start, i
        last_rule, last_end = None, i
        while j < len(text):
            state = table.step(state, text[j])
            if state == table.trap:
                break
            j += 1
            if table.accept[state] is not None:
                last_rule, last_end = table.accept[state], j

        if last_rule is None:                # ни один токен здесь не начинается
            if error_end == i:               # продолжение предыдущей ошибки - приклеиваем
                prev = tokens[-1]
                tokens[-1] = prev._replace(lexeme=prev.lexeme + text[i])
            else:
                tokens.append(Token("ERROR", text[i], line, col, "error"))
            end = error_end = i + 1
        else:
            rule = table.rules[last_rule]
            if rule["kind"] != "skip" or keep_skipped:
                tokens.append(Token(rule["name"], text[i:last_end], line, col, rule["kind"]))
            end = last_end

        for ch in text[i:end]:               # пересчёт строки и столбца
            line, col = (line + 1, 1) if ch == "\n" else (line, col + 1)
        i = end
    return tokens
