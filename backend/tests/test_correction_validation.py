"""Validation tests for model payloads and the resulting report."""

from __future__ import annotations

import pytest

from app.correction.scheme import SchemeBlueprint, SchemeQuestion
from app.correction.validation import validate_model_output
from app.engine import InvalidEngineOutput, REPORT_COMPLETED, REPORT_PARTIAL


def blueprint(*rows) -> SchemeBlueprint:
    questions = tuple(
        SchemeQuestion(label=label, max_marks=marks, max_marks_confident=confident)
        for label, marks, confident in rows
    )
    return SchemeBlueprint(questions=questions, coverage_checked=bool(questions))


def question(label="1(a)", awarded=1, out_of=2, status="marked", **extra):
    data = {
        "label": label,
        "status": status,
        "awarded": awarded,
        "out_of": out_of,
        "feedback": "",
        "criteria": [],
        "review_flags": [],
        "warnings": [],
    }
    data.update(extra)
    return data


def validate(payload, scheme=None):
    return validate_model_output(
        payload,
        blueprint=scheme if scheme is not None else blueprint(("1(a)", 2, True)),
        job_id="job-1",
        engine_name="test-engine",
        created_at="2026-01-01T00:00:00+00:00",
    )


def test_complete_report_recomputes_totals_and_percentage() -> None:
    report = validate(
        {
            "summary": "Two questions marked.",
            "questions": [
                question("1(a)", awarded=2, out_of=2, student_answer="5", scheme_answer="5"),
                question("1(b)", awarded=1, out_of=2),
            ],
            "warnings": [],
        },
        scheme=blueprint(("1(a)", 2, True), ("1(b)", 2, True)),
    )

    assert report.status == REPORT_COMPLETED
    assert report.awarded == 3
    assert report.out_of == 4
    assert report.percentage == 75.0
    assert report.job_id == "job-1"
    assert report.engine == "test-engine"
    assert report.created_at == "2026-01-01T00:00:00+00:00"
    assert report.unresolved == ()


def test_unresolved_question_makes_the_report_partial_without_a_percentage() -> None:
    report = validate(
        {
            "summary": "",
            "questions": [
                question("1(a)", awarded=2, out_of=2),
                question("1(b)", awarded=None, out_of=2, status="unreadable"),
            ],
        },
        scheme=blueprint(("1(a)", 2, True), ("1(b)", 2, True)),
    )

    assert report.status == REPORT_PARTIAL
    assert report.percentage is None
    assert report.unresolved == ("1(b)",)
    assert report.awarded == 2
    assert report.out_of == 4


def test_missing_question_is_synthesised_as_unresolved_not_zero() -> None:
    report = validate(
        {"summary": "", "questions": [question("1(a)", awarded=2, out_of=2)]},
        scheme=blueprint(("1(a)", 2, True), ("1(b)", 3, True)),
    )

    assert report.status == REPORT_PARTIAL
    missing = next(item for item in report.items if item.label == "1(b)")
    assert missing.awarded is None
    assert missing.out_of == 3
    assert missing.status == "unresolved"
    assert "No marking result" in missing.feedback
    assert any("no result was returned" in warning for warning in report.warnings)
    assert report.percentage is None


def test_confident_scheme_maximum_corrects_the_marker() -> None:
    report = validate(
        {"summary": "", "questions": [question("1(a)", awarded=2, out_of=3)]},
        scheme=blueprint(("1(a)", 2, True)),
    )

    assert report.items[0].out_of == 2
    assert report.percentage == 100.0
    assert any("maximum corrected" in warning for warning in report.warnings)


def test_weak_scheme_hint_does_not_override_the_marker() -> None:
    report = validate(
        {"summary": "", "questions": [question("1(a)", awarded=2, out_of=3)]},
        scheme=blueprint(("1(a)", 2, False)),
    )

    assert report.items[0].out_of == 3
    assert any("was kept" in warning for warning in report.warnings)


def test_award_above_a_confident_scheme_maximum_is_rejected() -> None:
    with pytest.raises(InvalidEngineOutput, match="mark scheme maximum"):
        validate(
            {"summary": "", "questions": [question("1(a)", awarded=3, out_of=3)]},
            scheme=blueprint(("1(a)", 2, True)),
        )


def test_award_above_the_reported_maximum_is_rejected() -> None:
    with pytest.raises(InvalidEngineOutput, match="maximum"):
        validate({"summary": "", "questions": [question("1(a)", awarded=3, out_of=2)]})


def test_marked_question_without_a_numeric_mark_is_rejected() -> None:
    with pytest.raises(InvalidEngineOutput, match="no numeric mark"):
        validate({"summary": "", "questions": [question("1(a)", awarded=None)]})


def test_negative_and_non_numeric_marks_are_rejected() -> None:
    with pytest.raises(InvalidEngineOutput, match="negative"):
        validate({"summary": "", "questions": [question("1(a)", awarded=-1, out_of=2)]})
    with pytest.raises(InvalidEngineOutput, match="not a number"):
        validate({"summary": "", "questions": [question("1(a)", awarded="1", out_of=2)]})
    with pytest.raises(InvalidEngineOutput, match="not a number"):
        validate({"summary": "", "questions": [question("1(a)", awarded=True, out_of=2)]})


def test_parent_and_child_together_are_rejected_to_prevent_double_counting() -> None:
    with pytest.raises(InvalidEngineOutput, match="double-counted"):
        validate(
            {
                "summary": "",
                "questions": [
                    question("1", awarded=5, out_of=5),
                    question("1(a)", awarded=2, out_of=2),
                ],
            },
            scheme=blueprint(("1", 5, True)),
        )


def test_duplicate_labels_are_rejected() -> None:
    with pytest.raises(InvalidEngineOutput, match="more than once"):
        validate(
            {
                "summary": "",
                "questions": [
                    question("1(a)", awarded=1, out_of=2),
                    question("1 (a)", awarded=2, out_of=2),
                ],
            }
        )


def test_no_questions_is_rejected() -> None:
    with pytest.raises(InvalidEngineOutput, match="no question results"):
        validate({"summary": "", "questions": []})


def test_mark_on_an_unresolved_question_is_dropped_and_reported() -> None:
    report = validate(
        {
            "summary": "",
            "questions": [
                question("1(a)", awarded=2, out_of=2, status="unreadable"),
                question("1(b)", awarded=1, out_of=1),
            ],
        },
        scheme=blueprint(("1(a)", 2, True), ("1(b)", 1, True)),
    )

    assert report.items[0].awarded is None
    assert any("was not accepted" in warning for warning in report.warnings)
    assert report.status == REPORT_PARTIAL


def test_subquestions_cover_a_parent_scheme_row() -> None:
    report = validate(
        {
            "summary": "",
            "questions": [
                question("1(a)", awarded=2, out_of=2),
                question("1(b)", awarded=3, out_of=3),
            ],
        },
        scheme=blueprint(("1", 5, True)),
    )

    assert report.unresolved == ()
    assert not any("not in the extracted scheme blueprint" in warning for warning in report.warnings)
    assert report.status == REPORT_COMPLETED
    assert report.out_of == 5


def test_subquestion_maxima_must_add_up_to_a_parent_total() -> None:
    report = validate(
        {
            "summary": "",
            "questions": [
                question("1(a)", awarded=2, out_of=2),
                question("1(b)", awarded=2, out_of=2),
            ],
        },
        scheme=blueprint(("1", 5, True)),
    )

    assert report.status == REPORT_PARTIAL
    assert report.percentage is None
    assert report.out_of == 4
    assert report.review_required is True
    assert any("subquestions total 4 marks" in warning for warning in report.warnings)


def test_a_parent_row_does_not_cover_missing_subquestions() -> None:
    report = validate(
        {"summary": "", "questions": [question("1", awarded=5, out_of=5)]},
        scheme=blueprint(("1(a)", 2, True), ("1(b)", 3, True)),
    )

    assert report.status == REPORT_PARTIAL
    assert set(report.unresolved) == {"1(a)", "1(b)"}
    assert any("not in the extracted scheme blueprint" in warning for warning in report.warnings)


def test_extra_question_is_kept_but_flagged_for_review() -> None:
    report = validate(
        {
            "summary": "",
            "questions": [
                question("1(a)", awarded=2, out_of=2),
                question("9", awarded=1, out_of=1),
            ],
        },
        scheme=blueprint(("1(a)", 2, True)),
    )

    extra = next(item for item in report.items if item.label == "9")
    assert "question_mapping_uncertain" in extra.review_flags
    assert any("not in the extracted scheme blueprint" in warning for warning in report.warnings)
    assert report.review_required is True


def test_items_are_sorted_naturally() -> None:
    report = validate(
        {
            "summary": "",
            "questions": [
                question("10", awarded=1, out_of=1),
                question("2(b)", awarded=1, out_of=1),
                question("1(a)", awarded=1, out_of=1),
            ],
        },
        scheme=SchemeBlueprint(questions=(), coverage_checked=False),
    )
    assert [item.label for item in report.items] == ["1(a)", "2(b)", "10"]
    assert report.review_required is True  # coverage was not independently verified


def test_more_awarded_criteria_than_marks_is_flagged_without_changing_the_mark() -> None:
    report = validate(
        {
            "summary": "",
            "questions": [
                question(
                    "1(a)",
                    awarded=1,
                    out_of=1,
                    criteria=[
                        {"code": "M1", "awarded": True, "reason": "method"},
                        {"code": "A1", "awarded": True, "reason": "answer"},
                    ],
                )
            ],
        },
        scheme=blueprint(("1(a)", 1, True)),
    )

    assert report.items[0].awarded == 1
    assert "mark_allocation_review" in report.items[0].review_flags
    assert any("criteria are marked as awarded" in warning for warning in report.warnings)


def test_partial_report_never_carries_a_percentage() -> None:
    report = validate(
        {"summary": "", "questions": [question("1(a)", awarded=1, out_of=2)]},
        scheme=SchemeBlueprint(questions=(), coverage_checked=False),
    )
    # The single question is complete, but coverage was not verified; marks and
    # percentage are still valid because no question is unresolved.
    assert report.status == REPORT_COMPLETED
    assert report.percentage == 50.0
    assert report.review_required is True
