import hashlib
import re
from pathlib import Path

from docx import Document
from docx.text.paragraph import Paragraph
from pypdf import PdfReader


def stable_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def extract_sections(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are unsupported. Upload a text-based, unencrypted file.")
        sections = [{"text": page.extract_text() or "", "page": i + 1,
                     "section": f"Page {i + 1}"} for i, page in enumerate(reader.pages)]
    elif suffix == ".docx":
        doc = Document(path)
        sections, title, lines = [], "Document", []
        # DOCX pagination depends on the renderer. Preserve sections, never invent pages.
        for item in doc.iter_inner_content():
            if isinstance(item, Paragraph):
                if item.style and item.style.name.startswith("Heading"):
                    if lines:
                        sections.append({"text": "\n".join(lines), "page": None, "section": title})
                        lines = []
                    title = item.text
                lines.append(item.text)
            else:
                lines.extend(" | ".join(cell.text for cell in row.cells) for row in item.rows)
        if lines:
            sections.append({"text": "\n".join(lines), "page": None, "section": title})
    elif suffix == ".txt":
        text = path.read_text(encoding="utf-8-sig")
        sections = [{"text": block, "page": None, "section": f"Section {i + 1}"}
                    for i, block in enumerate(re.split(r"\n\s*\n", text)) if block.strip()]
    else:
        raise ValueError("Supported file types are PDF, DOCX, and UTF-8 TXT.")
    if not any(section["text"].strip() for section in sections):
        raise ValueError("No extractable text found. Scanned documents require OCR before upload.")
    return sections


def make_chunks(document_id: str, sections: list[dict], size=1800, overlap=180):
    chunks = []
    for section in sections:
        text = section["text"].strip()
        for offset in range(0, len(text), size - overlap):
            piece = text[offset:offset + size]
            if not piece.strip():
                continue
            chunks.append({"id": stable_id(document_id, str(len(chunks))),
                           "document_id": document_id, "text": piece,
                           "page": section["page"], "section": section["section"],
                           "offset": offset})
    if len(chunks) > 500:
        raise ValueError("Document exceeds prototype limit of 500 chunks. Split it into smaller files.")
    return chunks
