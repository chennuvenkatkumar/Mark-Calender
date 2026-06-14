"""Local file ingestion for syllabus documents."""

from __future__ import annotations

from pathlib import Path


PDF_SUFFIXES = {".pdf"}
TEXT_SUFFIXES = {".txt", ".md"}


def extract_text(file_path: str | Path) -> str:
    """Return readable text from a local syllabus file."""

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Syllabus file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        return _extract_pdf_text(path)
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8")

    raise ValueError(f"Unsupported syllabus file type: {suffix or '<none>'}")


def _extract_pdf_text(path: Path) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - dependency error path
        raise ImportError(
            "PyMuPDF is required to ingest PDF syllabi. Install the 'pymupdf' package."
        ) from exc

    document = fitz.open(path)
    try:
        pages = [page.get_text("text") for page in document]
    finally:
        document.close()

    return "\n".join(page.strip() for page in pages if page.strip())
