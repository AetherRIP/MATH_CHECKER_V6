"""Deterministic verification tests (numeric, algebraic, review flags)."""

from __future__ import annotations

from app.correction.verify import (
    answers_equivalent,
    expressions_equivalent,
    parse_numeric,
    verify_items,
)
from app.engine import MarkedItem


def test_numeric_answers_share_one_value() -> None:
    assert parse_numeric("3/4") == 0.75
    assert parse_numeric("0.75") == 0.75
    assert parse_numeric("75%") == 0.75
    assert parse_numeric("1 1/2") == 1.5
    assert parse_numeric("-1 1/2") == -1.5
    assert parse_numeric("1,200") == 1200
    assert parse_numeric("£3.50") == 3.5
    assert parse_numeric("-£3.50") == -3.5
    assert parse_numeric("5 cm") == 5
    assert parse_numeric("x = 7") == 7
    assert parse_numeric("two") is None
    assert parse_numeric("") is None


def test_equivalent_fractions_and_units_agree() -> None:
    assert answers_equivalent("3/4", "0.75") == (True, "Numeric values agree (0.75).")
    assert answers_equivalent("5 cm", "5")[0] is True
    assert answers_equivalent("50%", "0.5")[0] is True
    assert answers_equivalent("2", "3")[0] is False


def test_algebraic_equivalence_is_checked_by_sampling() -> None:
    assert expressions_equivalent("2(x+1)", "2x+2") is True
    assert expressions_equivalent("x^2", "x*x") is True
    assert expressions_equivalent("(x+1)(x-1)", "x^2-1") is True
    assert expressions_equivalent("2(x+1)", "x+2") is False


def test_non_expression_text_is_inconclusive() -> None:
    assert expressions_equivalent("a correct expression", "x+1") is None
    assert answers_equivalent("", "5")[0] is None
    assert answers_equivalent("x+1", "y+1")[0] is None


def item(**overrides) -> MarkedItem:
    base = dict(
        label="1(a)",
        awarded=2.0,
        out_of=2.0,
        feedback="",
        status="marked",
        student_answer="5",
        scheme_answer="5",
    )
    base.update(overrides)
    return MarkedItem(**base)


def test_verification_never_changes_a_mark() -> None:
    items, warnings = verify_items((item(awarded=2.0, student_answer="6", scheme_answer="5"),))
    assert items[0].awarded == 2.0
    assert items[0].out_of == 2.0
    assert "mark_allocation_review" in items[0].review_flags
    assert any("full marks" in warning for warning in warnings)


def test_matching_answer_with_zero_marks_is_flagged_for_review() -> None:
    items, warnings = verify_items((item(awarded=0.0, student_answer="5", scheme_answer="5"),))
    assert items[0].awarded == 0.0
    assert "mark_allocation_review" in items[0].review_flags
    assert any("no marks" in warning for warning in warnings)


def test_agreeing_answers_record_evidence_without_a_flag() -> None:
    items, warnings = verify_items((item(awarded=1.0, student_answer="3/4", scheme_answer="0.75"),))
    assert "values agree" in items[0].verification
    assert items[0].review_flags == ()
    assert warnings == ()


def test_unreadable_items_are_left_alone() -> None:
    unreadable = item(awarded=None, status="unreadable", student_answer="", scheme_answer="5")
    items, warnings = verify_items((unreadable,))
    assert items[0].status == "unreadable"
    assert items[0].awarded is None
    assert warnings == ()
