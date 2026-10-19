"""Minimal, dependency-free PDF writer for deterministic tests.

It produces a real one-column text PDF with a standard Helvetica font so the
engine's pypdf extraction path is exercised for real, not mocked.
"""

from __future__ import annotations

from pathlib import Path


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def make_pdf(pages: list[str], *, path: Path) -> Path:
    """Write a valid PDF where each entry of ``pages`` becomes one text page."""
    if not pages:
        raise ValueError("At least one page is required.")

    objects: dict[int, bytes] = {}
    page_numbers = [4 + index * 2 for index in range(len(pages))]

    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{number} 0 R" for number in page_numbers)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    for index, text in enumerate(pages):
        page_number = page_numbers[index]
        content_number = page_number + 1
        objects[page_number] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 3 0 R >> >> "
            + f"/Contents {content_number} 0 R >>".encode()
        )
        lines = [_escape(line) for line in text.splitlines()] or [""]
        stream_parts = ["BT", "/F1 12 Tf", "50 800 Td", "58 TL"]
        for line in lines:
            stream_parts.append(f"({line}) Tj")
            stream_parts.append("T*")
        stream_parts.append("ET")
        stream = "\n".join(stream_parts).encode("latin-1", "replace")
        objects[content_number] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(output)
        output += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"

    max_number = max(objects)
    xref_offset = len(output)
    output += f"xref\n0 {max_number + 1}\n".encode()
    output += b"0000000000 65535 f \n"
    for number in range(1, max_number + 1):
        output += f"{offsets[number]:010d} 00000 n \n".encode()
    output += (
        f"trailer\n<< /Size {max_number + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()

    path.write_bytes(bytes(output))
    return path


def make_encrypted_pdf(path: Path, password: str = "secret") -> Path:
    """Write a real password-protected PDF using pypdf."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.encrypt(password)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def make_empty_pdf(path: Path) -> Path:
    """Write a structurally valid PDF with no pages."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    with path.open("wb") as handle:
        writer.write(handle)
    return path
