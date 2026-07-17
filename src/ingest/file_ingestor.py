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


def extract_text_from_bytes(data: bytes, filename: str) -> str:
    """Return readable text from a file already loaded into memory as bytes.

    Used by the web server where the uploaded file is never written to disk.
    Dispatches to the same extractors as extract_text() based on the filename
    extension so behaviour is identical to the path-based version.

    Raises ValueError for unsupported or empty content.
    """
    suffix = Path(filename).suffix.lower()

    if not data:
        raise ValueError("Uploaded file is empty.")

    if suffix in PDF_SUFFIXES:
        return _extract_pdf_bytes(data)

    if suffix in TEXT_SUFFIXES:
        return data.decode("utf-8")

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


def _extract_pdf_bytes(data: bytes) -> str:
    """Extract text from a PDF given as raw bytes using PyMuPDF.

    Opens the document from the in-memory byte stream so no temp file is
    ever written to disk.  Same page-joining logic as _extract_pdf_text().
    """
    try:
        import fitz
    except ImportError as exc:
        raise ImportError(
            "PyMuPDF is required to ingest PDF syllabi. Install the 'pymupdf' package."
        ) from exc

    document = fitz.open(stream=data, filetype="pdf")
    try:
        pages = [page.get_text("text") for page in document]
    finally:
        document.close()

    return "\n".join(page.strip() for page in pages if page.strip())
