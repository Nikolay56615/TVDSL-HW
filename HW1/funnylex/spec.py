"""Чтение файла tokens.spec.

Строка файла:   <вид> <ИМЯ> = <регулярное выражение до конца строки>
    вид = token  - обычный токен;
          skip   - распознать и выбросить (пробелы, комментарии);
          error  - «ошибочный токен»: распознаётся, чтобы выдать понятную ошибку.
Пустые строки и строки с '#' пропускаются. Порядок строк = приоритет:
если строка подходит под два правила, побеждает верхнее.
"""

from collections import namedtuple

from . import regex

Rule = namedtuple("Rule", "name kind pattern tree")


def parse_spec(text):
    """Текст tokens.spec -> список правил Rule (в порядке приоритета)."""
    rules = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            head, pattern = line.split("=", 1)     # первый '=' отделяет заголовок от выражения
            kind, name = head.split()
        except ValueError:
            raise ValueError("строка %d: ожидалось '<вид> <ИМЯ> = <выражение>'" % lineno)
        if kind not in ("token", "skip", "error"):
            raise ValueError("строка %d: вид должен быть token, skip или error" % lineno)
        if any(rule.name == name for rule in rules):
            raise ValueError("строка %d: имя %s уже занято" % (lineno, name))
        pattern = pattern.strip()
        try:
            tree = regex.parse(pattern)
        except regex.RegexError as error:
            raise ValueError("строка %d: %s" % (lineno, error))
        rules.append(Rule(name, kind, pattern, tree))
    if not rules:
        raise ValueError("в файле правил нет ни одного правила")
    return rules


def load_spec(path):
    with open(path, encoding="utf-8") as f:
        return parse_spec(f.read())
