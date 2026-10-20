"""Document validation and extraction for the correction engine.

The engine never trusts a filename or a browser-supplied media type. Every
file is checked on disk:

* it exists and is a regular, readable file of a supported type;
* its bytes match the declared media type (PDF, PNG or JPEG);
* PDFs open, are not password-protected, and have at least one page;
* page text is extracted with page numbers preserved;
* content that cannot be read is reported, never silently skipped.

No temporary files are created here: documents are read from the paths the
caller owns, and the extracted text lives in memory for the duration of one
request. Phase 4 owns the upload workspace and its cleanup; this module never
deletes a caller's file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ..engine import (
    ACCEPTED_MEDIA_TYPES,
    MAX_FILE_BYTES,
    ExtractionError,
    SubmissionFile,
)

log = logging.getLogger("mathchecker.correction.documents")

# Bounds that keep one request predictable for a free-tier provider.
MAX_PAGES = 200
MAX_TEXT_CHARS_PER_DOCUMENT = 60_000
MAX_TEXT_CHARS_PER_PAGE = 12_000

_PDF_MAGIC = b"%PDF-"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


@dataclass(frozen=True)
class ExtractedPage:
    """One page's extractable text. ``has_text`` is False for scans/images."""

    number: int
    text: str
    has_text: bool


@dataclass(frozen=True)
class ExtractedDocument:
    """A validated document plus everything extracted from it.

    ``path`` is server-side only and must not appear in API responses.
    """

    role: str  # "submission" | "mark_scheme"
    path: Path
    filename: str
    media_type: str
    size_bytes: int
    page_count: int
    pages: tuple[ExtractedPage, ...]
    text: str
    warnings: tuple[str, ...] = ()

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())

    @property
    def is_pdf(self) -> bool:
        return self.media_type == "application/pdf"


def sniff_media_type(path: Path) -> str | None:
    """Return the media type implied by the file's first bytes, or None."""
    try:
        with path.open("rb") as handle:
            header = handle.read(8)
    except OSError:
        return None
    if header.startswith(_PDF_MAGIC):
        return "application/pdf"
    if header.startswith(_PNG_MAGIC):
        return "image/png"
    if header.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    return None


def extract_document(file: SubmissionFile, role: str) -> ExtractedDocument:
    """Validate one file and extract what can be read from it.

    Raises :class:`ExtractionError` with a user-safe message for missing,
    empty, oversized, mislabelled, corrupt or password-protected files.
    """
    if role not in ("submission", "mark_scheme"):
        raise ValueError(f"Unknown document role: {role}")

    path = Path(file.path)
    try:
        if not path.is_file():
            raise ExtractionError(f"'{file.filename}' could not be read.")
        size_bytes = path.stat().st_size
    except OSError as exc:
        raise ExtractionError(f"'{file.filename}' could not be read.") from exc

    if size_bytes <= 0:
        raise ExtractionError(f"'{file.filename}' is empty.")
    if size_bytes > MAX_FILE_BYTES:
        raise ExtractionError(f"'{file.filename}' is larger than the 25 MB limit.")

    sniffed = sniff_media_type(path)
    if sniffed is None:
        raise ExtractionError(
            f"'{file.filename}' is not a readable PDF, PNG or JPEG file."
        )
    if file.media_type != sniffed:
        raise ExtractionError(
            f"'{file.filename}' does not match its declared file type ({file.media_type})."
        )

    if sniffed == "application/pdf":
        return _extract_pdf(file, path, size_bytes, role)
    return _extract_image(file, path, size_bytes, role)


def _extract_pdf(
    file: SubmissionFile, path: Path, size_bytes: int, role: str
) -> ExtractedDocument:
    warnings: list[str] = []
    try:
        reader = PdfReader(str(path), strict=False)
    except (PdfReadError, ValueError, OSError) as exc:
        log.warning("pdf open failed for %s (%s)", role, type(exc).__name__)
        raise ExtractionError(
            f"'{file.filename}' could not be opened as a PDF. The file may be corrupt."
        ) from exc

    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception:  # pypdf raises several crypto-specific types
            unlocked = 0
        if not unlocked:
            raise ExtractionError(
                f"'{file.filename}' is password-protected and cannot be read."
            )
        warnings.append(f"'{file.filename}' was encrypted with an empty password and was unlocked.")

    try:
        page_count = len(reader.pages)
    except Exception as exc:  # malformed page tree
        log.warning("pdf page tree failed for %s (%s)", role, type(exc).__name__)
        raise ExtractionError(
            f"'{file.filename}' has an unreadable page structure."
        ) from exc

    if page_count == 0:
        raise ExtractionError(f"'{file.filename}' contains no pages.")
    if page_count > MAX_PAGES:
        raise ExtractionError(
            f"'{file.filename}' has {page_count} pages; the limit for one document is {MAX_PAGES}."
        )

    pages: list[ExtractedPage] = []
    chunks: list[str] = []
    total_chars = 0
    truncated = False

    for index, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception as exc:  # a single bad page must not lose the document
            log.warning("pdf page text failed (%s page %s: %s)", role, index, type(exc).__name__)
            warnings.append(f"Page {index} of '{file.filename}' could not be read.")
            raw = ""

        # Keep logical line breaks: the mark-scheme blueprint anchors question
        # rows at the start of a line, and collapsing a whole page into one
        # line would hide every question after the first. Within a line,
        # whitespace is still normalised.
        text = "\n".join(
            " ".join(line.split()) for line in raw.splitlines() if line.strip()
        )
        if len(text) > MAX_TEXT_CHARS_PER_PAGE:
            text = text[:MAX_TEXT_CHARS_PER_PAGE]
            warnings.append(
                f"Page {index} of '{file.filename}' was truncated to the first "
                f"{MAX_TEXT_CHARS_PER_PAGE} characters of extractable text."
            )
        if not text:
            warnings.append(
                f"Page {index} of '{file.filename}' has no extractable text "
                "(it may be handwritten, a diagram or a scan)."
            )
        else:
            remaining = MAX_TEXT_CHARS_PER_DOCUMENT - total_chars
            if remaining <= 0:
                truncated = True
                text = ""
            elif len(text) > remaining:
                text = text[:remaining]
                truncated = True
            total_chars += len(text)
            chunks.append(f"--- page {index} ---\n{text}")
        pages.append(ExtractedPage(number=index, text=text, has_text=bool(text)))

    if truncated:
        warnings.append(
            f"'{file.filename}' exceeded the {MAX_TEXT_CHARS_PER_DOCUMENT}-character "
            "extraction limit; later text was truncated."
        )

    if not chunks:
        warnings.append(
            f"'{file.filename}' contains no extractable text; it will be interpreted visually."
        )

    return ExtractedDocument(
        role=role,
        path=path,
        filename=file.filename,
        media_type="application/pdf",
        size_bytes=size_bytes,
        page_count=page_count,
        pages=tuple(pages),
        text="\n\n".join(chunks),
        warnings=tuple(warnings),
    )


def _extract_image(
    file: SubmissionFile, path: Path, size_bytes: int, role: str
) -> ExtractedDocument:
    # The bytes were already checked against the declared type. Images carry
    # their content visually; there is no text extraction step to pretend to
    # perform here.
    return ExtractedDocument(
        role=role,
        path=path,
        filename=file.filename,
        media_type=file.media_type,
        size_bytes=size_bytes,
        page_count=1,
        pages=(ExtractedPage(number=1, text="", has_text=False),),
        text="",
    )


def read_document_bytes(document: ExtractedDocument) -> bytes:
    """Read a validated document for inline provider transmission."""
    try:
        data = document.path.read_bytes()
    except OSError as exc:
        raise ExtractionError(f"'{document.filename}' could not be read.") from exc
    if not data:
        raise ExtractionError(f"'{document.filename}' is empty.")
    return data


def check_media_type_supported(media_type: str) -> bool:
    return media_type in ACCEPTED_MEDIA_TYPES
