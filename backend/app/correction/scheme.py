"""Deterministic mark-scheme structure extraction.

The model reads the full mark scheme; this module extracts a conservative
question blueprint from the extractable text. The blueprint is used to:

* tell the model the expected question labels and maximum marks;
* detect questions the model returned no result for;
* correct a maximum mark that contradicts the supplied scheme;
* decide whether the final result is complete.

Extraction is heuristic. When it finds nothing, marking still proceeds from
the supplied document, but coverage is NOT independently verified and the
report says so. A parsing failure must never be mistaken for a complete
mark scheme.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .documents import ExtractedDocument

_ROMAN = r"(?:i|ii|iii|iv|v|vi|vii|viii|ix|x)"
_LABEL = rf"\d{{1,3}}(?:\([a-z]\))?(?:\({_ROMAN}\))?"

# A label at the start of a line, optionally preceded by "Question" or "Q"
# as many published schemes write "Question 1 (3 marks): ...". The negative
# lookahead prevents matching a word such as "1st"; a label may legitimately
# end with ")".
_LABEL_LINE = re.compile(
    rf"^\s*(?:(?P<prefix>Question|Q)\.?\s*)?(?P<label>{_LABEL})(?![0-9A-Za-z])",
    re.IGNORECASE,
)

# Explicit total-mark notations, strongest first. A bare trailing number is
# accepted as a hint but NOT as a confident maximum: a mark-scheme line may
# end with a value from the working rather than the question total.
#
# Parenthesised marks are searched anywhere on the line because schemes often
# follow them with a colon and the question text; the bracket and bare-number
# forms stay anchored so ordinary body text is not mistaken for a total.
_MARK_PATTERNS = (
    (re.compile(r"\((\d{1,2})\s*marks?\)", re.IGNORECASE), True),
    (re.compile(r"\[(\d{1,2})\]\s*(?:[:.]|$)"), True),
    (re.compile(r"\(\s*(\d{1,2})\s*\)\s*(?:[:.]|$)"), True),
    (re.compile(r"(?:^|\s)(\d{1,2})\s*marks?\b", re.IGNORECASE), True),
    (re.compile(r"(?:^|\s)(\d{1,2})\s*$"), False),
)


@dataclass(frozen=True)
class SchemeQuestion:
    label: str
    max_marks: float | None
    max_marks_confident: bool = False

    def key(self) -> tuple:
        return label_sort_key(self.label)


def _marks_from_line(line: str) -> tuple[float | None, bool]:
    for pattern, confident in _MARK_PATTERNS:
        match = pattern.search(line)
        if not match:
            continue
        marks = float(int(match.group(1)))
        if marks <= 0 or marks > 40:
            continue
        return marks, confident
    return None, False


@dataclass(frozen=True)
class SchemeBlueprint:
    """Questions extracted from the mark scheme, in document order."""

    questions: tuple[SchemeQuestion, ...]
    warnings: tuple[str, ...] = ()
    coverage_checked: bool = False

    def question_for(self, label: str) -> SchemeQuestion | None:
        wanted = normalise_label(label)
        for question in self.questions:
            if question.label == wanted:
                return question
        return None

    def max_for(self, label: str) -> float | None:
        question = self.question_for(label)
        return question.max_marks if question else None

    def max_is_confident(self, label: str) -> bool:
        question = self.question_for(label)
        return bool(question and question.max_marks is not None and question.max_marks_confident)

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(question.label for question in self.questions)

    def prompt_block(self) -> str:
        if not self.questions:
            return ""
        lines = ["## Question blueprint extracted from the mark scheme"]
        for question in self.questions:
            marks = (
                f"{_format_marks(question.max_marks)} marks"
                if question.max_marks is not None
                else "maximum not detected"
            )
            lines.append(f"- {question.label}: {marks}")
        lines.append(
            "These labels and maxima were read from the mark scheme. Return one "
            "entry for every label. Do not change a maximum that is stated here."
        )
        return "\n".join(lines)


def normalise_label(value: str) -> str:
    """Normalise a question label to the form the blueprint uses.

    ``"1 (a) (i)"`` -> ``"1(a)(i)"``; case is normalised but nothing else is
    invented, so an unknown label stays visibly unknown.
    """
    text = re.sub(r"\s+", "", str(value or "")).strip(".:;-—–")
    return text.lower()


def label_sort_key(label: str) -> tuple:
    """Natural order for labels such as 1, 1(a), 1(a)(i), 2(a)."""
    text = normalise_label(label)
    match = re.match(
        rf"^(\d+)(?:\(([a-z])\))?(?:\(({_ROMAN})\))?$",
        text,
        re.IGNORECASE,
    )
    if not match:
        return (9999, text, 0, 0)
    number = int(match.group(1))
    letter = ord(match.group(2)) - 96 if match.group(2) else 0
    roman = _roman_value(match.group(3)) if match.group(3) else 0
    return (number, "", letter, roman)


def _roman_value(token: str) -> int:
    values = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
    return values.get(token.lower(), 0)


def _format_marks(value: float) -> str:
    return f"{value:g}"


def build_blueprint(
    documents: list[ExtractedDocument], extra_text: str = ""
) -> SchemeBlueprint:
    """Extract the question blueprint from mark-scheme documents and pasted text.

    Conflicting maxima for the same label are not guessed: the label keeps
    ``None`` and the conflict is reported.
    """
    warnings: list[str] = []
    found: dict[str, float | None] = {}
    confident: dict[str, bool] = {}
    conflicted: set[str] = set()
    order: list[str] = []

    sources: list[str] = []
    for document in documents:
        if not document.has_text:
            warnings.append(
                f"'{document.filename}' has no extractable text, so its question "
                "structure could not be checked."
            )
            continue
        sources.append(document.text)
    if extra_text.strip():
        sources.append(extra_text)

    for text in sources:
        for line in text.splitlines():
            if line.lstrip().startswith("--- page"):
                continue
            label_match = _LABEL_LINE.match(line)
            if not label_match:
                continue
            # "Question 1" on its own is a heading for its subquestions, not a
            # markable row; keeping it would invent a question with no maximum.
            if label_match.group("prefix") and not line[label_match.end():].strip(
                " \t:.-–—"
            ):
                continue
            label = normalise_label(label_match.group("label"))
            if label not in found:
                found[label] = None
                confident[label] = False
                order.append(label)

            marks, is_confident = _marks_from_line(line)
            if marks is None:
                continue
            if label in conflicted:
                continue
            current = found[label]
            if current is None:
                found[label] = marks
                confident[label] = is_confident
            elif current == marks:
                confident[label] = confident[label] or is_confident
            elif is_confident and not confident[label]:
                # A confident reading supersedes an earlier bare-number hint.
                found[label] = marks
                confident[label] = True
            elif confident[label] and not is_confident:
                # A weak hint cannot override an explicit total.
                continue
            else:
                warnings.append(
                    f"The mark scheme gives conflicting maxima for question {label} "
                    f"({_format_marks(current)} and {_format_marks(marks)}); "
                    "the maximum is treated as unknown."
                )
                found[label] = None
                confident[label] = False
                conflicted.add(label)

    questions = tuple(
        SchemeQuestion(
            label=label,
            max_marks=found[label],
            max_marks_confident=confident[label] if found[label] is not None else False,
        )
        for label in sorted(order, key=label_sort_key)
    )
    if not questions:
        warnings.append(
            "No question structure could be extracted from the mark scheme text; "
            "question coverage will be reported but not independently verified."
        )
    return SchemeBlueprint(
        questions=questions,
        warnings=tuple(warnings),
        coverage_checked=bool(questions),
    )
