"""Mark-scheme blueprint extraction tests."""

from __future__ import annotations

from pathlib import Path

from app.correction.documents import ExtractedDocument, ExtractedPage, extract_document
from app.correction.scheme import build_blueprint, label_sort_key, normalise_label
from app.engine import SubmissionFile
from pdf_factory import make_pdf


def scheme_document(path: Path, text: str) -> ExtractedDocument:
    return ExtractedDocument(
        role="mark_scheme",
        path=path,
        filename=path.name,
        media_type="application/pdf",
        size_bytes=len(text.encode()),
        page_count=1,
        pages=(ExtractedPage(number=1, text=text, has_text=True),),
        text=text,
    )


def test_extracts_labels_and_maxima_from_scheme_rows(tmp_path: Path) -> None:
    document = scheme_document(
        tmp_path / "scheme.pdf",
        "\n".join(
            [
                "Question 1",
                "1(a)  2",
                "1(b)(i)  1",
                "1(b)(ii)  (3 marks)",
                "2  5",
                "Total: 11",
            ]
        ),
    )
    blueprint = build_blueprint([document])

    assert blueprint.coverage_checked is True
    assert blueprint.labels == ("1(a)", "1(b)(i)", "1(b)(ii)", "2")
    assert blueprint.max_for("1(a)") == 2
    assert blueprint.max_for("1(b)(ii)") == 3
    assert blueprint.max_for("2") == 5
    # An explicit "(3 marks)" is trusted; a bare trailing number is only a hint.
    assert blueprint.max_is_confident("1(b)(ii)") is True
    assert blueprint.max_is_confident("1(a)") is False
    assert "Question blueprint" in blueprint.prompt_block()


def test_published_question_prefix_with_trailing_colon(tmp_path: Path) -> None:
    """A real Edexcel-style layout ("Question 1 (3 marks): ...") is parsed.

    This mirrors the bundled V5 fixture scheme, where the mark notation is
    followed by a colon and the question text rather than ending the line.
    """
    path = make_pdf(
        [
            "\n".join(
                [
                    "Fixture Mark Scheme - Edexcel-style quiz (10 marks)",
                    "Total: 10 marks",
                    "Question 1 (3 marks): Solve 4x + 7 = 31.",
                    "  M1: Subtract 7 from both sides.",
                    "Question 2 (2 marks): Write 0.36 as a fraction.",
                    "Question 3 (3 marks): The nth term is 3n - 2.",
                    "Question 4 (2 marks): Work out (2^3)^2.",
                ]
            )
        ],
        path=tmp_path / "published.pdf",
    )
    document = extract_document(
        SubmissionFile(
            path=path,
            filename="published.pdf",
            media_type="application/pdf",
            size_bytes=path.stat().st_size,
        ),
        "mark_scheme",
    )

    blueprint = build_blueprint([document])

    assert blueprint.coverage_checked is True
    assert blueprint.labels == ("1", "2", "3", "4")
    assert [blueprint.max_for(label) for label in blueprint.labels] == [3, 2, 3, 2]
    assert all(blueprint.max_is_confident(label) for label in blueprint.labels)
    assert sum(question.max_marks or 0 for question in blueprint.questions) == 10


def test_conflicting_maxima_are_unknown_and_reported(tmp_path: Path) -> None:
    document = scheme_document(
        tmp_path / "scheme.pdf",
        "1(a)  2\n1(a)  3\n1(b)  1",
    )
    blueprint = build_blueprint([document])

    assert blueprint.max_for("1(a)") is None
    assert any("conflicting maxima" in warning for warning in blueprint.warnings)


def test_missing_structure_is_not_treated_as_verified(tmp_path: Path) -> None:
    document = scheme_document(tmp_path / "scheme.pdf", "Mark as follows: award one mark.")
    blueprint = build_blueprint([document])

    assert blueprint.questions == ()
    assert blueprint.coverage_checked is False
    assert any("No question structure" in warning for warning in blueprint.warnings)


def test_scheme_without_extractable_text_is_flagged(tmp_path: Path) -> None:
    path = make_pdf([""], path=tmp_path / "scan.pdf")
    document = extract_document(
        SubmissionFile(path=path, filename="scan.pdf", media_type="application/pdf", size_bytes=path.stat().st_size),
        "mark_scheme",
    )
    blueprint = build_blueprint([document])

    assert blueprint.coverage_checked is False
    assert any("no extractable text" in warning for warning in blueprint.warnings)


def test_labels_are_normalised_without_inventing_structure() -> None:
    assert normalise_label(" 1 (a) (i) ") == "1(a)(i)"
    assert normalise_label("2(b)") == "2(b)"
    assert normalise_label("Unknown") == "unknown"


def test_labels_sort_in_question_order() -> None:
    labels = ["10", "2(b)", "1(a)(ii)", "1(a)(i)", "1", "2(a)"]
    assert sorted(labels, key=label_sort_key) == ["1", "1(a)(i)", "1(a)(ii)", "2(a)", "2(b)", "10"]
