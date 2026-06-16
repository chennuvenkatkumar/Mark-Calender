"""Local file ingestion for syllabus documents."""

from __future__ import annotations

from pathlib import Path


# Supported binary document formats that require PyMuPDF for text extraction
PDF_SUFFIXES = {".pdf"}

# Supported plain-text formats that can be read directly with UTF-8 decoding
TEXT_SUFFIXES = {".txt", ".md"}


def extract_text(file_path: str | Path) -> str:
    """Return readable text extracted from a local syllabus file.

    Dispatches to the appropriate extractor based on the file extension.
    Raises FileNotFoundError if the path does not exist, and ValueError
    for unsupported extensions.

    Usage:
        text = extract_text("syllabus.pdf")
        text = extract_text(Path("syllabus.txt"))
    """

    # Normalise the incoming path so both str and Path objects are accepted
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Syllabus file not found: {path}")

    suffix = path.suffix.lower()

    # Route to the PDF extractor for binary PDF files
    if suffix in PDF_SUFFIXES:
        return _extract_pdf_text(path)

    # Plain-text and Markdown files can be read directly without an extra library
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8")

    raise ValueError(f"Unsupported syllabus file type: {suffix or '<none>'}")


def _extract_pdf_text(path: Path) -> str:
    """Extract and return all text content from a PDF file using PyMuPDF.

    Opens each page in the document, collects its text, strips blank pages,
    and joins all pages with newlines into a single string.

    Raises ImportError if the 'pymupdf' package is not installed.
    """

    # Guard against missing optional dependency — give a clear install hint
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - dependency error path
        raise ImportError(
            "PyMuPDF is required to ingest PDF syllabi. Install the 'pymupdf' package."
        ) from exc

    # Open the PDF and always close it in the finally block to free file handles
    document = fitz.open(path)
    try:
        # "text" mode returns plain text without layout coordinates
        pages = [page.get_text("text") for page in document]
    finally:
        document.close()

    # Drop blank pages before joining so the output text has no empty sections
    return "\n".join(page.strip() for page in pages if page.strip())
