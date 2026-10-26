"""Общие правила арифметики для исполнения IR и свёртки констант."""


def i32(value):
    """Переполнение целого с теми же 32 битами, что у JVM int."""
    return (value + (1 << 31)) % (1 << 32) - (1 << 31)


def evaluate_unary(operator, value):
    if operator == "-":
        return i32(-i32(value))
    if operator == "not":
        return not value
    raise ValueError("Неизвестная унарная операция %r" % operator)


def evaluate_binary(operator, left, right):
    if operator in {"and", "or", "->"}:
        return {"and": left and right, "or": left or right,
                "->": not left or right}[operator]
    left, right = i32(left), i32(right)
    if operator == "+":
        return i32(left + right)
    if operator == "-":
        return i32(left - right)
    if operator == "*":
        return i32(left * right)
    if operator == "/":
        if right == 0:
            raise ZeroDivisionError("Деление на ноль")
        # // округляет вниз, а Funny/JVM делят с округлением к нулю.
        quotient = abs(left) // abs(right)
        return i32(-quotient if (left < 0) != (right < 0) else quotient)
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    if operator == "<":
        return left < right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    if operator == ">=":
        return left >= right
    raise ValueError("Неизвестная бинарная операция %r" % operator)
