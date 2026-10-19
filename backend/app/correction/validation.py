"""Validation of a marking response into a typed, consistent report.

Everything the model returns is untrusted. This module owns the rules that
turn a JSON payload into :class:`app.engine.CorrectionReport`:

* labels are normalised, must be unique, and are matched to the blueprint;
* marks must be real, finite, non-negative numbers no greater than the
  question maximum;
* a question the model did not return is added as *unresolved*, never as 0;
* maxima that contradict an unambiguous mark-scheme maximum are corrected to
  the scheme value and reported;
* totals are recomputed from the accepted question marks — the model's own
  totals are ignored;
* a percentage is produced only for a complete report with a positive total;
* impossible or contradictory output is rejected instead of being stored.
"""

from __future__ import annotations

import math

from ..engine import (
    QUESTION_AMBIGUOUS,
    QUESTION_MARKED,
    QUESTION_MISSING,
    QUESTION_STATUSES,
    QUESTION_UNREADABLE,
    QUESTION_UNRESOLVED,
    REPORT_COMPLETED,
    REPORT_PARTIAL,
    CorrectionReport,
    InvalidEngineOutput,
    MarkedItem,
)
from .scheme import SchemeBlueprint, label_sort_key, normalise_label

_MAX_MARK = 1000.0
_MAX_LIST = 40
_MAX_TEXT = 4000


def _text(value, limit: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _text_list(value, limit: int = _MAX_LIST) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for entry in value[:limit]:
        if isinstance(entry, str):
            text = entry.strip()[:500]
            if text and text not in result:
                result.append(text)
    return tuple(result)


def _number(value, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidEngineOutput(f"{field} was not a number.")
    number = float(value)
    if not math.isfinite(number):
        raise InvalidEngineOutput(f"{field} was not a finite number.")
    if number < 0:
        raise InvalidEngineOutput(f"{field} was negative.")
    if number > _MAX_MARK:
        raise InvalidEngineOutput(f"{field} was implausibly large.")
    return number


def _format_criteria(value) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    criteria: list[str] = []
    for entry in value[:_MAX_LIST]:
        if isinstance(entry, str):
            text = entry.strip()[:500]
        elif isinstance(entry, dict):
            code = _text(entry.get("code"), 40)
            reason = _text(entry.get("reason"), 500)
            awarded = entry.get("awarded")
            if isinstance(awarded, bool):
                state = "awarded" if awarded else "not awarded"
            else:
                state = "evidence" if not code else "recorded"
            text = f"{code} ({state}): {reason}".strip() if code else reason
        else:
            continue
        if text and text not in criteria:
            criteria.append(text)
    return tuple(criteria)


def _clean_label(value, index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidEngineOutput(f"Question {index} had no label.")
    label = normalise_label(value)
    if not label:
        raise InvalidEngineOutput(f"Question {index} had no label.")
    return label


def _status(value, awarded: float | None, index: int) -> str:
    if value is None:
        return QUESTION_MARKED if awarded is not None else QUESTION_UNRESOLVED
    if not isinstance(value, str):
        raise InvalidEngineOutput(f"Question {index} had an invalid status.")
    status = value.strip().lower()
    if status not in QUESTION_STATUSES:
        raise InvalidEngineOutput(f"Question {index} had an unknown status.")
    return status


def _is_child_label(label: str, parent: str) -> bool:
    """True when ``label`` is a subquestion of ``parent`` (1 vs 1(a))."""
    return label.startswith(parent + "(")


def _parent_is_covered(parent: str, seen: set[str]) -> bool:
    """A parent question is covered when the marker returned its subquestions."""
    return any(_is_child_label(actual, parent) for actual in seen)


def _build_item(raw, index: int) -> tuple[MarkedItem, tuple[str, ...]]:
    if not isinstance(raw, dict):
        raise InvalidEngineOutput(f"Question {index} was not an object.")

    label = _clean_label(raw.get("label", raw.get("question_number")), index)
    out_of = _number(raw.get("out_of", raw.get("max_marks")), f"Question {label} maximum")
    awarded = _number(raw.get("awarded", raw.get("awarded_marks")), f"Question {label} award")
    status = _status(raw.get("status"), awarded, index)
    warnings: list[str] = []

    if status == QUESTION_MARKED:
        if awarded is None:
            raise InvalidEngineOutput(
                f"Question {label} was marked but carried no numeric mark."
            )
        if out_of is not None and awarded > out_of:
            raise InvalidEngineOutput(
                f"Question {label} awarded {awarded:g} marks but its maximum is {out_of:g}."
            )
    elif awarded is not None:
        warnings.append(
            f"Question {label} had status '{status}' but carried a mark; the mark was not accepted."
        )
        awarded = None

    if out_of is None:
        warnings.append(f"Question {label}: the maximum mark could not be determined.")

    item = MarkedItem(
        label=label,
        awarded=awarded,
        out_of=out_of,
        feedback=_text(raw.get("feedback") or raw.get("loss_reason")),
        criteria=_format_criteria(raw.get("criteria") or raw.get("mark_breakdown")),
        student_evidence=_text(raw.get("student_evidence") or raw.get("working_summary")),
        scheme_evidence=_text(raw.get("scheme_evidence")),
        student_answer=_text(raw.get("student_answer"), 300),
        scheme_answer=_text(raw.get("scheme_answer"), 300),
        status=status,
        warnings=_text_list(raw.get("warnings")),
        review_flags=_text_list(raw.get("review_flags")),
    )
    return item, tuple(warnings)


def _append_unique(values: tuple[str, ...], additions) -> tuple[str, ...]:
    result = list(values)
    for addition in additions:
        if addition and addition not in result:
            result.append(addition)
    return tuple(result)


def validate_model_output(
    payload: dict,
    *,
    blueprint: SchemeBlueprint,
    job_id: str,
    engine_name: str,
    created_at: str,
) -> CorrectionReport:
    """Validate one marking payload and return a consistent report."""
    if not isinstance(payload, dict):
        raise InvalidEngineOutput("The AI provider returned a response that was not an object.")

    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise InvalidEngineOutput("The AI provider returned no question results.")

    warnings: list[str] = list(_text_list(payload.get("warnings")))
    warnings.extend(blueprint.warnings)

    items: list[MarkedItem] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_questions, start=1):
        item, item_warnings = _build_item(raw, index)
        if item.label in seen:
            raise InvalidEngineOutput(
                f"The AI provider returned question {item.label} more than once."
            )
        seen.add(item.label)
        warnings.extend(item_warnings)
        items.append(item)

    for label in seen:
        for other in seen:
            if label != other and _is_child_label(other, label):
                raise InvalidEngineOutput(
                    f"The AI provider returned question {label} and its subquestion "
                    f"{other}; their marks would be double-counted."
                )

    mapping_issue = False
    expected = set(blueprint.labels)
    if expected:
        for label in blueprint.labels:
            if label in seen or _parent_is_covered(label, seen):
                # Returning 1(a), 1(b) to a scheme row "1" is valid coverage;
                # it is not a missing question and not a set of extra rows.
                continue
            question = next(q for q in blueprint.questions if q.label == label)
            items.append(
                MarkedItem(
                    label=label,
                    awarded=None,
                    out_of=question.max_marks,
                    feedback="No marking result was returned for this question.",
                    status=QUESTION_UNRESOLVED,
                    review_flags=("question_mapping_uncertain",),
                    warnings=("The mark scheme declares this question but the marker returned nothing.",),
                )
            )
            warnings.append(
                f"Question {label} is in the mark scheme but no result was returned; "
                "it is unresolved, not a confirmed zero."
            )

        extra = sorted(
            (
                label
                for label in seen - expected
                # A subquestion of a declared parent is not an extra question.
                if not any(_is_child_label(label, parent) for parent in expected)
            ),
            key=label_sort_key,
        )
        for label in extra:
            warnings.append(
                f"Question {label} was marked but is not in the extracted scheme blueprint; "
                "verify the mapping before trusting it."
            )
            items = [
                _with_review_flag(item, "question_mapping_uncertain") if item.label == label else item
                for item in items
            ]

        # Correct a maximum that contradicts an unambiguous scheme maximum.
        corrected: list[MarkedItem] = []
        for item in items:
            scheme_max = blueprint.max_for(item.label)
            if scheme_max is None:
                corrected.append(item)
                continue
            if item.out_of is None:
                corrected.append(_with_max(item, scheme_max))
                warnings.append(
                    f"Question {item.label}: maximum filled in from the mark scheme ({scheme_max:g})."
                )
            elif item.out_of != scheme_max and blueprint.max_is_confident(item.label):
                if item.awarded is not None and item.awarded > scheme_max:
                    raise InvalidEngineOutput(
                        f"Question {item.label} awarded {item.awarded:g} marks but the "
                        f"mark scheme maximum is {scheme_max:g}."
                    )
                corrected.append(_with_max(item, scheme_max))
                warnings.append(
                    f"Question {item.label}: maximum corrected from {item.out_of:g} to the "
                    f"mark-scheme value {scheme_max:g}."
                )
            elif item.out_of != scheme_max:
                # The extracted value was only a hint (for example a bare
                # trailing number). Keep the marker's value and surface the
                # disagreement rather than rewriting a maximum on a guess.
                warnings.append(
                    f"Question {item.label}: the marker reported a maximum of "
                    f"{item.out_of:g}, while the extracted scheme hint was {scheme_max:g}; "
                    "the marker's value was kept because the extraction was not confident."
                )
                corrected.append(item)
            else:
                corrected.append(item)
        items = corrected

        # When a parent scheme row is covered by subquestions, their maxima
        # should add up to the parent total. A mismatch is evidence of a
        # mapping problem, not a reason to rewrite any question maximum.
        for question in blueprint.questions:
            if question.max_marks is None or question.label in seen:
                continue
            children = [
                item
                for item in items
                if _is_child_label(item.label, question.label)
            ]
            if children and all(item.out_of is not None for item in children):
                child_total = float(sum(item.out_of for item in children if item.out_of is not None))
                if child_total != question.max_marks:
                    mapping_issue = True
                    warnings.append(
                        f"Question {question.label}: its subquestions total "
                        f"{child_total:g} marks, but the mark scheme states "
                        f"{question.max_marks:g}. Verify the question mapping."
                    )

    items.sort(key=lambda item: label_sort_key(item.label))

    # A criterion breakdown that claims more awarded marks than the question
    # is worth is contradictory evidence, not a reason to change the mark.
    for index, item in enumerate(items):
        if item.out_of is None:
            continue
        awarded_criteria = sum(1 for text in item.criteria if "(awarded)" in text)
        if awarded_criteria > item.out_of:
            items[index] = _with_review_flag(item, "mark_allocation_review")
            warnings.append(
                f"Question {item.label}: {awarded_criteria} criteria are marked as awarded "
                f"but the question is worth {item.out_of:g}; review the breakdown."
            )

    # A question with a review flag still keeps its mark; only its status
    # distinguishes an unreadable or missing answer.
    for index, item in enumerate(items):
        if item.status != QUESTION_MARKED and item.awarded is not None:
            items[index] = MarkedItem(
                **{**item.__dict__, "awarded": None}
            )
            warnings.append(
                f"Question {item.label}: a mark was dropped because the question is {item.status}."
            )

    unresolved = tuple(item.label for item in items if item.status != QUESTION_MARKED)
    unknown_max = any(item.out_of is None for item in items)
    complete = (
        not unresolved
        and not mapping_issue
        and not unknown_max
        and all(item.awarded is not None for item in items)
    )

    awarded_values = [item.awarded for item in items if item.awarded is not None]
    # A partial report exposes the sum of the marks that were actually
    # accepted. It is deliberately not presented as a final score; the status
    # and absent percentage say so.
    total_awarded = float(sum(awarded_values)) if awarded_values else None
    total_out_of = (
        float(sum(item.out_of for item in items if item.out_of is not None))
        if items and not unknown_max
        else None
    )
    percentage = None
    if complete and total_out_of and total_out_of > 0 and total_awarded is not None:
        percentage = round(total_awarded / total_out_of * 100.0, 2)

    review_required = bool(
        unresolved
        or mapping_issue
        or not blueprint.coverage_checked
        or any(item.review_flags for item in items)
    )

    return CorrectionReport(
        job_id=job_id,
        summary=_text(payload.get("summary"), 2000),
        awarded=total_awarded,
        out_of=total_out_of,
        items=tuple(items),
        status=REPORT_COMPLETED if complete else REPORT_PARTIAL,
        percentage=percentage,
        review_required=review_required,
        unresolved=unresolved,
        warnings=tuple(warnings),
        engine=engine_name,
        created_at=created_at,
    )


def _with_review_flag(item: MarkedItem, flag: str) -> MarkedItem:
    if flag in item.review_flags:
        return item
    return MarkedItem(
        **{**item.__dict__, "review_flags": (*item.review_flags, flag)}
    )


def _with_max(item: MarkedItem, value: float) -> MarkedItem:
    warnings = item.warnings
    if item.out_of is not None and item.out_of != value:
        warnings = (*warnings, f"Maximum corrected from {item.out_of:g} to {value:g}.")
    return MarkedItem(**{**item.__dict__, "out_of": value, "warnings": warnings})


# Re-exported so callers and tests do not need to import the ambiguous/missing
# constants from two modules.
__all__ = [
    "validate_model_output",
    "QUESTION_AMBIGUOUS",
    "QUESTION_MISSING",
    "QUESTION_UNREADABLE",
]
