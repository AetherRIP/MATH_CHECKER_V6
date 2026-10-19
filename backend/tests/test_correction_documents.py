"""Document validation/extraction tests for the correction engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.correction import documents as documents_module
from app.correction.documents import extract_document, read_document_bytes, sniff_media_type
from app.engine import MAX_FILE_BYTES, ExtractionError, SubmissionFile
from pdf_factory import make_empty_pdf, make_encrypted_pdf, make_pdf


def submission(path: Path, media_type: str = "application/pdf", filename: str | None = None) -> SubmissionFile:
    return SubmissionFile(
        path=path,
        filename=filename or path.name,
        media_type=media_type,
        size_bytes=path.stat().st_size,
    )


def test_extracts_text_and_page_numbers_from_a_real_pdf(tmp_path: Path) -> None:
    path = make_pdf(["Question 1\nAnswer: 4", "Question 2\nAnswer: x = 7"], path=tmp_path / "work.pdf")
    document = extract_document(submission(path), "submission")

    assert document.role == "submission"
    assert document.media_type == "application/pdf"
    assert document.page_count == 2
    assert document.pages[0].number == 1
    assert "Question 1" in document.pages[0].text
    assert "x = 7" in document.pages[1].text
    assert document.has_text is True
    assert document.warnings == ()


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    missing = SubmissionFile(
        path=tmp_path / "gone.pdf",
        filename="gone.pdf",
        media_type="application/pdf",
        size_bytes=10,
    )
    with pytest.raises(ExtractionError, match="could not be read"):
        extract_document(missing, "submission")


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    with pytest.raises(ExtractionError, match="empty"):
        extract_document(submission(path), "submission")


def test_oversized_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "big.pdf"
    path.write_bytes(b"%PDF-1.4\n" + b"0" * (MAX_FILE_BYTES + 1))
    with pytest.raises(ExtractionError, match="25 MB"):
        extract_document(submission(path), "submission")


def test_mislabelled_file_is_rejected(tmp_path: Path) -> None:
    path = make_pdf(["hello"], path=tmp_path / "actually.pdf")
    with pytest.raises(ExtractionError, match="does not match its declared file type"):
        extract_document(submission(path, media_type="image/png"), "submission")


def test_file_with_no_recognisable_header_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "notes.pdf"
    path.write_bytes(b"just some text, not a document")
    with pytest.raises(ExtractionError, match="not a readable PDF, PNG or JPEG"):
        extract_document(submission(path), "submission")


def test_corrupt_pdf_is_reported_not_silently_skipped(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.7\nthis is not a pdf body\n")
    with pytest.raises(ExtractionError, match="could not be opened as a PDF|unreadable page structure|no pages"):
        extract_document(submission(path), "submission")


def test_pdf_with_no_pages_is_rejected(tmp_path: Path) -> None:
    path = make_empty_pdf(tmp_path / "empty-pages.pdf")
    with pytest.raises(ExtractionError, match="no pages"):
        extract_document(submission(path), "submission")


def test_password_protected_pdf_is_reported(tmp_path: Path) -> None:
    path = make_encrypted_pdf(tmp_path / "locked.pdf", "secret")
    with pytest.raises(ExtractionError, match="password-protected"):
        extract_document(submission(path), "submission")


def test_pdf_without_extractable_text_is_flagged(tmp_path: Path) -> None:
    path = make_pdf([""], path=tmp_path / "scan.pdf")
    document = extract_document(submission(path), "submission")
    assert document.has_text is False
    assert document.page_count == 1
    assert any("no extractable text" in warning.lower() for warning in document.warnings)


def test_png_and_jpeg_are_accepted_as_visual_documents(tmp_path: Path) -> None:
    png = tmp_path / "page.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    jpeg = tmp_path / "page.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff" + b"0" * 64)

    png_document = extract_document(submission(png, "image/png"), "submission")
    jpeg_document = extract_document(submission(jpeg, "image/jpeg"), "submission")

    assert png_document.page_count == 1
    assert png_document.has_text is False
    assert jpeg_document.media_type == "image/jpeg"
    assert sniff_media_type(png) == "image/png"
    assert sniff_media_type(jpeg) == "image/jpeg"


def test_a_page_that_cannot_be_read_is_reported_without_losing_the_document(
    tmp_path: Path, monkeypatch
) -> None:
    path = make_pdf(["Question 1"], path=tmp_path / "work.pdf")

    class BrokenPage:
        def extract_text(self):
            raise RuntimeError("simulated extraction failure")

    class BrokenReader:
        is_encrypted = False
        pages = [BrokenPage()]

    monkeypatch.setattr(documents_module, "PdfReader", lambda *args, **kwargs: BrokenReader())

    document = extract_document(submission(path), "submission")

    assert document.page_count == 1
    assert document.has_text is False
    assert any("Page 1 of 'work.pdf' could not be read" in warning for warning in document.warnings)
    assert any("no extractable text" in warning.lower() for warning in document.warnings)


def test_mark_scheme_role_is_recorded(tmp_path: Path) -> None:
    path = make_pdf(["1(a)  2", "1(b)  1"], path=tmp_path / "scheme.pdf")
    document = extract_document(submission(path), "mark_scheme")
    assert document.role == "mark_scheme"


def test_read_bytes_returns_the_validated_content(tmp_path: Path) -> None:
    path = make_pdf(["hello"], path=tmp_path / "work.pdf")
    document = extract_document(submission(path), "submission")
    assert read_document_bytes(document).startswith(b"%PDF-")
