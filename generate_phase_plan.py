"""One-shot script -- generates the project phase plan PDF, then can be deleted."""

from fpdf import FPDF, XPos, YPos
from pathlib import Path


ACCENT  = (26,  86, 155)
LIGHT   = (240, 245, 255)
WHITE   = (255, 255, 255)
DARK    = (20,  20,  40)
GREY    = (100, 100, 110)
GREEN   = (30,  140, 80)
ORANGE  = (200, 100, 0)


class PhasePDF(FPDF):
    def header(self):
        self.set_fill_color(*ACCENT)
        self.rect(0, 0, 210, 18, "F")
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*WHITE)
        self.set_xy(0, 4)
        self.cell(210, 10, "Syllabus-to-Calendar AI  |  Project Phase Plan", align="C",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*DARK)
        self.ln(6)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 6, f"Page {self.page_no()}", align="C")

    def title_block(self):
        self.set_fill_color(*LIGHT)
        self.rect(10, 20, 190, 28, "F")
        self.set_xy(10, 22)
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(*ACCENT)
        self.cell(190, 10, "Development Phase Roadmap", align="C",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*GREY)
        self.set_x(10)
        self.cell(190, 8, "Iteration 1  ->  Iteration 2  ->  Iteration 3   |   June 2026",
                  align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(6)

    def section_header(self, label: str, color=None):
        if color is None:
            color = ACCENT
        self.set_fill_color(*color)
        self.set_text_color(*WHITE)
        self.set_font("Helvetica", "B", 11)
        self.set_x(10)
        self.cell(190, 8, f"  {label}", fill=True,
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*DARK)
        self.ln(2)

    def phase_row(self, num: str, title: str, what: str, files: str, status: str = "pending"):
        status_color = GREEN if status == "done" else ORANGE if status == "bug" else GREY
        y_start = self.get_y()
        # Phase number badge
        self.set_fill_color(*ACCENT)
        self.set_text_color(*WHITE)
        self.set_font("Helvetica", "B", 9)
        self.set_xy(10, y_start)
        self.cell(12, 14, num, fill=True, align="C")
        # Title
        self.set_fill_color(250, 252, 255)
        self.set_text_color(*DARK)
        self.set_xy(22, y_start)
        self.set_font("Helvetica", "B", 9)
        self.cell(118, 6, f"  {title}", fill=True)
        # Status badge
        self.set_fill_color(*status_color)
        self.set_text_color(*WHITE)
        self.set_font("Helvetica", "B", 7)
        self.cell(50, 6, status.upper(), fill=True, align="C",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        # What line
        self.set_xy(22, self.get_y())
        self.set_fill_color(250, 252, 255)
        self.set_text_color(*GREY)
        self.set_font("Helvetica", "", 8)
        self.cell(168, 4, f"  What: {what}", fill=True,
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        # Files line
        self.set_xy(22, self.get_y())
        self.set_font("Helvetica", "I", 8)
        self.cell(168, 4, f"  Files: {files}", fill=True,
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)

    def component_block(self, heading: str, components: list):
        self.set_x(10)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*ACCENT)
        self.cell(190, 6, heading, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*DARK)
        for tag, desc in components:
            self.set_x(14)
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*ACCENT)
            self.cell(30, 5, tag)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*DARK)
            self.multi_cell(156, 5, desc)
        self.ln(2)

    def note_box(self, text: str):
        self.set_fill_color(255, 248, 220)
        self.set_x(10)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(100, 70, 0)
        self.multi_cell(190, 5, text, fill=True, border=1)
        self.set_text_color(*DARK)
        self.ln(3)

    def continuity_section(self):
        self.section_header("How to Continue This Project in a New Chat Session")
        self.set_font("Helvetica", "", 9)
        self.set_x(10)
        steps = [
            ("Step 1", "Open a new Claude Code session in the same project folder."),
            ("Step 2", 'Say: "Check memory and continue the Syllabus-to-Calendar project from where we left off."'),
            ("Step 3", "Claude loads saved memory files from the .claude/projects/ folder and knows which phase is next."),
            ("Step 4", 'To skip memory, just say the phase directly: "Start Phase 1" or "Start Phase 2" etc.'),
            ("Step 5", "Memory folder: C:\\Users\\venkat\\.claude\\projects\\...\\memory\\"),
            ("Step 6", "Or paste this PDF into the new chat and say: \"here is the blueprint, continue from Phase X\""),
        ]
        for label, detail in steps:
            self.set_x(14)
            self.set_font("Helvetica", "B", 9)
            self.set_text_color(*ACCENT)
            self.cell(20, 6, label)
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*DARK)
            self.multi_cell(166, 6, detail)
        self.ln(2)
        self.note_box(
            "TIP: The memory system remembers what is done, what is broken, and what is next. "
            "You never need to re-explain the project. Claude will pick up exactly where you left off."
        )


def build_pdf(output_path: Path):
    pdf = PhasePDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(10, 20, 10)
    pdf.add_page()

    pdf.title_block()

    # Current state table
    pdf.section_header("Current State of Iteration 1 - What Exists")
    existing = [
        ("file_ingestor.py",            "Reads PDF (PyMuPDF) and TXT/MD files, returns clean text.", "DONE"),
        ("gemini_pipeline_controller.py","Builds JSON-enforced Gemini prompt, calls google-genai SDK.", "DONE"),
        ("string_validator.py",         "Extracts JSON block, normalises dates/times, validates fields.", "DONE"),
        ("icalendar_factory.py",        "Builds RFC-5545 .ics file. Had a truncated class name -- FIXED in P0.", "FIXED"),
    ]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(*ACCENT)
    pdf.set_text_color(*WHITE)
    pdf.set_x(10)
    pdf.cell(75, 6, "File", fill=True)
    pdf.cell(95, 6, "Purpose", fill=True)
    pdf.cell(20, 6, "State", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for fname, purpose, state in existing:
        c = GREEN if state == "DONE" else ORANGE
        pdf.set_fill_color(248, 250, 255)
        pdf.set_text_color(*DARK)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_x(10)
        pdf.cell(75, 5, fname)
        pdf.cell(95, 5, purpose[:68] + ("..." if len(purpose) > 68 else ""))
        pdf.set_fill_color(*c)
        pdf.set_text_color(*WHITE)
        pdf.set_font("Helvetica", "B", 7)
        pdf.cell(20, 5, state, fill=True, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*DARK)
    pdf.ln(4)

    # Phase plan table
    pdf.section_header("All Phases - Ordered Delivery Plan")

    phases = [
        ("P0",  "Phase 0 - Bug Fix (COMPLETE)",
         "Repair truncated ExportResult class name + remove duplicate tail lines in icalendar_factory.py",
         "src/export/icalendar_factory.py",
         "done"),
        ("P1A", "Phase 1A - requirements.txt",
         "Add dependency file (pymupdf, google-genai, fastapi, uvicorn) so project is installable",
         "requirements.txt  (new file)",
         "pending"),
        ("P1B", "Phase 1B - CLI Runner (main.py)",
         "Wire all 4 I1 modules into one command: python main.py syllabus.pdf",
         "main.py  (new file)",
         "pending"),
        ("P2",  "Phase 2 - FastAPI Backend",
         "POST /process: accept file upload, run full pipeline, return extracted events as JSON",
         "server/main.py  (new file)",
         "pending"),
        ("P3",  "Phase 3 - Frontend Upload Page",
         "Drag-and-drop HTML page with TailwindCSS CDN. Sends file to /process via fetch()",
         "frontend/index.html  (new file)",
         "pending"),
        ("P4",  "Phase 4 - Interactive Event Table",
         "Render editable rows per event. Fields: course, task, date, time, description + delete button",
         "frontend/index.html  (extend)",
         "pending"),
        ("P5",  "Phase 5 - ICS Download Trigger",
         "POST /download returns .ics stream. Browser Download button triggers file-save dialog",
         "server/main.py + frontend/index.html  (extend both)",
         "pending"),
        ("P6",  "Phase 6 - Integration Polish",
         "Test with a real PDF. Add graceful 429 rate-limit message and empty-syllabus fallback UI",
         "server/main.py + frontend/index.html  (extend both)",
         "pending"),
        ("P7",  "Phase 7 - Iteration 3 (Future)",
         "Google OAuth 2.0 direct push, rate-limit queue middleware, auto-retry error interceptor",
         "server/ + frontend/  (extend)",
         "pending"),
    ]

    for num, title, what, files, status in phases:
        pdf.phase_row(num, title, what, files, status)

    # Page 2
    pdf.add_page()
    pdf.section_header("Iteration 2 - Component Detail (Phases 2 through 6)")

    pdf.component_block(
        "Backend  server/main.py  --  Phases 2 and 5",
        [
            ("[POST /process]",
             "Accepts multipart file upload. Reads file bytes into memory (never saves to disk -- privacy). "
             "Routes PDF bytes through PyMuPDF in-memory extractor -> Gemini pipeline -> JSON validator. "
             "Returns list of normalised event objects as JSON response."),
            ("[POST /download]",
             "Accepts the (possibly edited) events JSON sent from the browser table. "
             "Runs it through build_ics() from the existing icalendar_factory module. "
             "Returns the .ics string as an HTTP response with Content-Type: text/calendar "
             "and Content-Disposition: attachment so the browser saves it automatically."),
        ]
    )

    pdf.component_block(
        "Frontend  frontend/index.html  --  Phases 3, 4 and 5",
        [
            ("[Upload Zone]",
             "Drag-and-drop file boundary styled with TailwindCSS CDN (no npm, no build step). "
             "Accepts PDF and TXT. Shows spinner/loading state while fetch() waits for /process."),
            ("[Event Table]",
             "Renders one editable row per extracted event. "
             "Columns: course name, task name, date (date picker input), time, description. "
             "Each row has a red delete button to remove incorrect entries."),
            ("[Download Button]",
             "Appears below the table after events load. "
             "POSTs the current table state (including any edits) to /download "
             "and the browser receives the .ics file as a download."),
            ("[Error Banner]",
             "Displays clean, user-readable messages for API errors, rate-limit 429 response, "
             "empty syllabus, or corrupted PDF. Never shows a raw stack trace to the user."),
        ]
    )

    pdf.continuity_section()

    # Tech stack
    pdf.section_header("Tech Stack Quick Reference")
    stack = [
        ("PyMuPDF (fitz)",   "PDF text extraction -- local, free, no external cloud needed"),
        ("google-genai",     "Official Google Gen AI Python SDK for Gemini 1.5 Flash API calls"),
        ("FastAPI + Uvicorn","Async Python web server for the /process and /download endpoints"),
        ("TailwindCSS CDN",  "Utility CSS via <script> tag -- zero npm, zero build step"),
        ("fpdf2",            "PDF generation for this plan document only -- not part of the app"),
    ]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(*ACCENT)
    pdf.set_text_color(*WHITE)
    pdf.set_x(10)
    pdf.cell(50, 6, "Library", fill=True)
    pdf.cell(140, 6, "Role", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    toggle = False
    for lib, role in stack:
        pdf.set_fill_color(245, 248, 255) if not toggle else pdf.set_fill_color(255, 255, 255)
        pdf.set_text_color(*DARK)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_x(10)
        pdf.cell(50, 5, lib, fill=True)
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(140, 5, role, fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        toggle = not toggle
    pdf.set_text_color(*DARK)
    pdf.ln(4)

    pdf.output(str(output_path))
    print(f"PDF saved -> {output_path}")


if __name__ == "__main__":
    out = Path(__file__).parent / "SyllabusCalendar_PhasePlan.pdf"
    build_pdf(out)
