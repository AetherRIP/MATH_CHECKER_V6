"""Deterministic answer verification.

This module re-checks what can be checked without an AI: numeric equality
(exact values, fractions, decimals, percentages, simple units) and algebraic
equivalence by numeric sampling. It is deliberately conservative.

HARD RULE: verification never changes a mark. It records evidence and raises
review flags when a marking decision conflicts with a check that *could* be
performed. When a check is not possible it says so; it never pretends the
mathematics was verified.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import replace
from typing import Iterable

from ..engine import (
    QUESTION_MARKED,
    MarkedItem,
)

_REL_TOLERANCE = 1e-6
_SAMPLE_VALUES = (0.7, 1.3, 2.2, -1.1, 3.7, 5.1)

_UNICODE_REPLACEMENTS = {
    "\u2212": "-",
    "\u00d7": "*",
    "\u00f7": "/",
    "\u00b2": "^2",
    "\u00b3": "^3",
    "\u221a": "sqrt",
    "\u03c0": "pi",
}

_UNIT_PATTERN = re.compile(
    r"\s*(?:cm|mm|km|kg|mg|ml|mph|m/s|m|g|l|s|min|h|degrees?|deg|°c|°f|°|cm2|cm²|m2|m²)\s*$",
    re.IGNORECASE,
)
_FRACTION = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*/\s*([+-]?\d+(?:\.\d+)?)$")
_MIXED = re.compile(r"^([+-]?\d+)\s+(\d+)\s*/\s*(\d+)$")
_NUMBER = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def _strip_currency_and_spacing(text: str) -> str:
    value = text.strip()
    for source, target in _UNICODE_REPLACEMENTS.items():
        value = value.replace(source, target)
    value = value.replace("\u00a0", " ")
    value = re.sub(r"^([+-]?)\s*[£$€]\s*", r"\1", value)
    value = re.sub(r"\s*[£$€]$", "", value)
    return value.strip()


def _take_last_equality(text: str) -> str:
    if "=" not in text:
        return text
    parts = [part.strip() for part in text.split("=") if part.strip()]
    return parts[-1] if parts else text


def parse_numeric(text: str) -> float | None:
    """Parse a simple numeric answer, or return ``None``.

    Supports ``3/4``, ``1 1/2``, ``-0.75``, ``1,200`` and ``50%``. A unit may
    follow the number; it is ignored for value comparison (unit *requirements*
    are a mark-scheme matter, not something this helper can judge).
    """
    if not text:
        return None
    value = _strip_currency_and_spacing(str(text))
    value = _take_last_equality(value)
    value = value.strip().strip("()[]")
    percent = value.endswith("%")
    if percent:
        value = value[:-1].strip()
    value = _UNIT_PATTERN.sub("", value)
    value = value.replace(",", "")

    mixed = _MIXED.match(value)
    if mixed:
        whole = float(mixed.group(1))
        fraction = float(mixed.group(2)) / float(mixed.group(3))
        number = whole - fraction if whole < 0 else whole + fraction
    else:
        fraction = _FRACTION.match(value)
        if fraction:
            denominator = float(fraction.group(2))
            if denominator == 0:
                return None
            number = float(fraction.group(1)) / denominator
        elif _NUMBER.match(value):
            try:
                number = float(value)
            except ValueError:
                return None
        else:
            return None

    if not math.isfinite(number):
        return None
    return number / 100.0 if percent else number


def _close(left: float, right: float) -> bool:
    if left == right:
        return True
    scale = max(abs(left), abs(right), 1.0)
    return abs(left - right) <= _REL_TOLERANCE * scale


# --- Algebraic equivalence ---------------------------------------------------


def _normalise_expression(text: str) -> str:
    value = _strip_currency_and_spacing(text)
    value = _take_last_equality(value)
    value = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"((\1)/(\2))", value)
    value = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"sqrt(\1)", value)
    value = value.replace("\\left", "").replace("\\right", "")
    value = value.replace("{", "").replace("}", "")
    value = re.sub(r"\s+", " ", value).strip()
    # A small amount of implicit multiplication: 2(x+1), 2x, (x+1)(x-1).
    value = re.sub(r"(?<=\d)\s*\(", "*(", value)
    value = re.sub(r"(?<=\d)\s*(?=[a-zA-Z])", "*", value)
    value = re.sub(r"\)\s*(?=[\da-zA-Z(])", ")*", value)
    return value


def _compile_expression(text: str) -> tuple[ast.Expression, set[str]] | None:
    normalised = _normalise_expression(text)
    if not normalised:
        return None
    python_text = normalised.replace("^", "**")
    try:
        tree = ast.parse(python_text, mode="eval")
    except SyntaxError:
        return None

    names: set[str] = set()

    def visit(node: ast.AST) -> bool:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
        if isinstance(node, ast.BinOp):
            return isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod)) and visit(node.left) and visit(node.right)
        if isinstance(node, ast.UnaryOp):
            return isinstance(node.op, (ast.UAdd, ast.USub)) and visit(node.operand)
        if isinstance(node, ast.Name):
            names.add(node.id)
            return True
        if isinstance(node, ast.Call):
            return (
                isinstance(node.func, ast.Name)
                and node.func.id in {"sqrt", "abs"}
                and len(node.args) == 1
                and not node.keywords
                and visit(node.args[0])
            )
        return False

    if not visit(tree):
        return None
    return tree, names


def _evaluate(tree: ast.Expression, variables: dict[str, float]) -> float | None:
    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id == "pi":
                return math.pi
            if node.id == "e":
                return math.e
            return variables[node.id]
        if isinstance(node, ast.UnaryOp):
            value = walk(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left = walk(node.left)
            right = walk(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Mod):
                return left % right
            return left**right
        if isinstance(node, ast.Call):
            argument = walk(node.args[0])
            return math.sqrt(argument) if node.func.id == "sqrt" else abs(argument)
        raise ValueError("unsupported expression")

    try:
        result = walk(tree)
    except (ArithmeticError, ValueError, KeyError):
        return None
    return result if math.isfinite(result) else None


def expressions_equivalent(left: str, right: str) -> bool | None:
    """Compare two simple algebraic expressions by numeric sampling.

    Returns ``None`` when either side is not a supported expression or the
    sample cannot decide. Supported: numbers, ``+ - * / ^ %``, parentheses,
    ``sqrt``, ``abs``, ``pi`` and free single-letter variables.
    """
    left_compiled = _compile_expression(left)
    right_compiled = _compile_expression(right)
    if not left_compiled or not right_compiled:
        return None
    left_tree, left_names = left_compiled
    right_tree, right_names = right_compiled

    if left_names != right_names:
        # Different free variables cannot be compared by sampling; treating
        # them as "not equivalent" would be a fabricated judgement.
        return None
    variables = (left_names | right_names) - {"pi", "e"}
    if len(variables) > 4:
        return None

    compared = 0
    for sample in _SAMPLE_VALUES:
        values = {name: sample + 0.31 * index for index, name in enumerate(sorted(variables))}
        left_value = _evaluate(left_tree, values)
        right_value = _evaluate(right_tree, values)
        if left_value is None or right_value is None:
            continue
        compared += 1
        if not _close(left_value, right_value):
            return False
    if compared < 2:
        return None
    return True


def answers_equivalent(student_answer: str, scheme_answer: str) -> tuple[bool | None, str]:
    """Return ``(equivalent, explanation)`` for two short answer strings."""
    student = str(student_answer or "").strip()
    scheme = str(scheme_answer or "").strip()
    if not student or not scheme:
        return None, "No comparable answer text was recorded."

    student_number = parse_numeric(student)
    scheme_number = parse_numeric(scheme)
    if student_number is not None and scheme_number is not None:
        if _close(student_number, scheme_number):
            return True, f"Numeric values agree ({student_number:g})."
        return False, f"Numeric values differ ({student_number:g} vs {scheme_number:g})."

    equivalent = expressions_equivalent(student, scheme)
    if equivalent is True:
        return True, "Expressions agree at sampled values."
    if equivalent is False:
        return False, "Expressions differ at sampled values."
    return None, "No deterministic comparison was possible."


# --- Item checking -----------------------------------------------------------


def _add_unique(values: Iterable[str], additions: Iterable[str]) -> tuple[str, ...]:
    result = list(values)
    for value in additions:
        if value and value not in result:
            result.append(value)
    return tuple(result)


def verify_items(items: tuple[MarkedItem, ...]) -> tuple[tuple[MarkedItem, ...], tuple[str, ...]]:
    """Annotate items with deterministic checks and return report warnings.

    Marks are copied through unchanged. A disagreement only adds a review flag
    and a warning; it never edits ``awarded``.
    """
    verified: list[MarkedItem] = []
    report_warnings: list[str] = []

    for item in items:
        if item.status != QUESTION_MARKED:
            verified.append(item)
            continue

        equivalent, detail = answers_equivalent(item.student_answer, item.scheme_answer)
        if equivalent is None:
            verified.append(replace(item, verification=detail))
            continue

        flags: list[str] = []
        warnings: list[str] = []
        if equivalent and item.out_of and item.awarded == 0:
            flags.append("mark_allocation_review")
            warnings.append(
                f"Question {item.label}: the recorded answer matches the mark-scheme "
                "answer but no marks were awarded. Review the method/accuracy split."
            )
        elif not equivalent and item.out_of and item.awarded == item.out_of:
            flags.append("mark_allocation_review")
            warnings.append(
                f"Question {item.label}: the recorded answer differs from the "
                "mark-scheme answer but full marks were awarded. Review whether an "
                "alternative method justifies every mark."
            )
        report_warnings.extend(warnings)
        verified.append(
            replace(
                item,
                verification=detail,
                review_flags=_add_unique(item.review_flags, flags),
                warnings=_add_unique(item.warnings, warnings),
            )
        )

    return tuple(verified), tuple(report_warnings)
