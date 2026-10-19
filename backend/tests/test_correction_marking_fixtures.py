"""Representative marking fixtures.

The decisions in this table are made by the model at run time. These tests do
not assert that a model would make them; they assert that when a decision is
reported, the pipeline preserves it, validates it, and computes totals and
completeness honestly.

The cases mirror the marking situations the engine must not flatten:
full credit, method-only credit, an incorrect final answer with valid working,
an arithmetic slip, an alternative method, follow-through, a confirmed blank,
and unreadable/ambiguous answers.
"""

from __future__ import annotations

import pytest

from app.correction.scheme import SchemeBlueprint, SchemeQuestion
from app.correction.validation import validate_model_output
from app.engine import InvalidEngineOutput, REPORT_COMPLETED, REPORT_PARTIAL


def scheme(max_marks: float = 3) -> SchemeBlueprint:
    return SchemeBlueprint(
        questions=(SchemeQuestion("1", max_marks, True),),
        coverage_checked=True,
    )


def item(awarded, status="marked", feedback="", criteria=None, flags=None):
    return {
        "label": "1",
        "status": status,
        "awarded": awarded,
        "out_of": 3,
        "feedback": feedback,
        "criteria": criteria or [],
        "review_flags": flags or [],
    }


def validate(question):
    return validate_model_output(
        {"summary": "", "questions": [question]},
        blueprint=scheme(),
        job_id="job",
        engine_name="test",
        created_at="2026-01-01T00:00:00+00:00",
    )


CASES = [
    ("correct answer with valid working", item(3, criteria=[{"code": "M1", "awarded": True, "reason": "method"}, {"code": "A2", "awarded": True, "reason": "answer"}]), 3.0, REPORT_COMPLETED),
    ("correct final answer with insufficient method evidence", item(1, feedback="Method marks not shown."), 1.0, REPORT_COMPLETED),
    ("incorrect final answer with valid method marks", item(2, feedback="Method correct; final value wrong."), 2.0, REPORT_COMPLETED),
    ("arithmetic slip after correct method", item(2, feedback="Correct method; arithmetic error in the last line."), 2.0, REPORT_COMPLETED),
    ("alternative valid method", item(3, feedback="Alternative method accepted."), 3.0, REPORT_COMPLETED),
    ("follow-through after an earlier error", item(2, feedback="Follow-through allowed."), 2.0, REPORT_COMPLETED),
    ("confirmed blank answer", item(0, feedback="Blank."), 0.0, REPORT_COMPLETED),
    ("unreadable answer", item(None, status="unreadable", feedback="Handwriting unclear."), None, REPORT_PARTIAL),
    ("ambiguous mark scheme", item(None, status="ambiguous", flags=["mark_scheme_ambiguous"]), None, REPORT_PARTIAL),
    ("missing answer row", item(None, status="missing"), None, REPORT_PARTIAL),
]


@pytest.mark.parametrize("name,question,awarded,status", CASES)
def test_representative_marking_decisions_are_preserved(name, question, awarded, status) -> None:
    report = validate(question)

    assert report.status == status, name
    assert report.items[0].awarded == awarded, name
    assert report.items[0].out_of == 3
    if awarded is None:
        assert report.percentage is None
    else:
        assert report.awarded == awarded
        if status == REPORT_COMPLETED:
            assert report.percentage == round(awarded / 3 * 100, 2)
        else:
            assert report.percentage is None


def test_award_above_the_maximum_is_rejected_in_a_fixture() -> None:
    with pytest.raises(InvalidEngineOutput):
        validate(item(4))


def test_model_feedback_and_criteria_are_preserved() -> None:
    report = validate(
        item(
            2,
            feedback="M1 awarded, A1 lost: 5.1 is not 5.",
            criteria=[{"code": "M1", "awarded": True, "reason": "correct substitution"}],
        )
    )
    assert report.items[0].feedback.startswith("M1 awarded")
    assert "correct substitution" in report.items[0].criteria[0]
