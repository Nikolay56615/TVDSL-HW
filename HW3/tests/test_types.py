"""Связывание неизвестных типов и откат неудачного присваивания."""

import unittest

from HW3.funnytypes.types import (ARRAY, BOOL, ERROR, INT, TypeVar,
                                  Unification, UnificationError, resolve, unify)


class UnificationTests(unittest.TestCase):
    def test_matching_primitives_and_conflicting_primitives(self):
        for value in (INT, ARRAY, BOOL):
            self.assertEqual(unify(value, value), value)
        for left, right in ((INT, ARRAY), (ARRAY, BOOL), (BOOL, INT)):
            with self.subTest(left=left, right=right):
                with self.assertRaises(UnificationError):
                    unify(left, right)

    def test_linked_unknowns_receive_same_concrete_type(self):
        first, second, third = (TypeVar(name) for name in ("first", "second", "third"))
        unify(first, second)
        unify(third, first)
        unify(second, ARRAY)
        self.assertEqual([resolve(value) for value in (first, second, third)], [ARRAY] * 3)

    def test_self_unification_does_not_create_a_cycle(self):
        first, second = TypeVar("first"), TypeVar("second")
        unify(first, first)
        unify(first, second)
        unify(second, first)
        self.assertIs(resolve(first), resolve(second))
        unify(first, INT)
        self.assertEqual(resolve(second), INT)

    def test_conflict_rolls_back_other_result_bindings(self):
        first, second = TypeVar("first"), TypeVar("second")
        assignment = Unification()
        assignment.unify(first, INT)
        assignment.unify(second, ARRAY)
        with self.assertRaises(UnificationError):
            assignment.unify(INT, ARRAY)
        assignment.rollback()
        self.assertIs(resolve(first), first)
        self.assertIs(resolve(second), second)

    def test_rollback_preserves_bindings_from_earlier_assignments(self):
        old, new = TypeVar("old"), TypeVar("new")
        unify(old, ARRAY)
        assignment = Unification()
        assignment.unify(new, old)
        assignment.rollback()
        self.assertEqual(resolve(old), ARRAY)
        self.assertIs(resolve(new), new)

    def test_committed_binding_survives_later_rollback(self):
        variable = TypeVar("variable")
        assignment = Unification()
        assignment.unify(variable, INT)
        assignment.commit()
        assignment.rollback()
        self.assertEqual(resolve(variable), INT)

    def test_error_does_not_bind_an_unknown_type(self):
        variable = TypeVar("variable")
        self.assertEqual(unify(variable, ERROR), ERROR)
        self.assertIs(resolve(variable), variable)
        self.assertEqual(unify(ERROR, ARRAY), ERROR)
        unify(variable, ARRAY)
        self.assertEqual(resolve(variable), ARRAY)


if __name__ == "__main__":
    unittest.main()
