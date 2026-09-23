"""Deterministic text extraction for ingested source files.

One extractor serves every adapter that receives binary documents (Gmail
attachments, Drive files), so a PDF yields the same text whichever way it
arrived. It never calls a model and never runs OCR: a PDF without a text
layer is reported as ``requires-ocr`` and left for a human decision.

Extracted text is untrusted evidence. It is sanitized for Markdown here, and
the documents built from it are marked ``content_trust: untrusted``; nothing
inside an imported file is ever treated as an instruction.
"""

from __future__ import annotations

import html
import io
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


#: Bump when extraction output changes, so stored results are rebuilt.
EXTRACTOR_VERSION = "document-text-v1"

STATUS_EXTRACTED = "extracted"
STATUS_REQUIRES_OCR = "requires-ocr"
STATUS_UNSUPPORTED = "unsupported"
STATUS_PASSWORD_PROTECTED = "password-protected"
STATUS_MALFORMED = "malformed"
STATUS_EMPTY = "empty"
STATUS_TOO_LARGE = "too-large"
STATUS_EXTRACTOR_UNAVAILABLE = "extractor-unavailable"

#: Outcomes worth retrying once the extractor, or its dependencies, change.
RETRYABLE_STATUSES = frozenset({STATUS_EXTRACTOR_UNAVAILABLE})

KIND_TEXT = "text"
KIND_MARKDOWN = "markdown"
KIND_PDF = "pdf"
KIND_DOCX = "docx"

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_MIME_TYPES = frozenset({"text/plain"})
MARKDOWN_MIME_TYPES = frozenset({"text/markdown", "text/x-markdown"})

#: Gmail caps attachments at 25 MB; Drive files can be larger.
MAX_EXTRACT_BYTES = 50 * 1024 * 1024

#: Fewer letters or digits than this across a whole PDF is not a text layer:
#: scanned pages often carry a stray page number or a producer stamp.
MIN_USABLE_PDF_CHARACTERS = 40

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_GENERIC_MIME_TYPES = frozenset({"", "application/octet-stream", "binary/octet-stream"})


@dataclass(frozen=True)
class Extraction:
    """What extraction produced for one payload, and why."""

    status: str
    kind: str = ""
    text: str = ""
    method: str = ""
    detail: str = ""
    pages: Optional[int] = None

    @property
    def extracted(self) -> bool:
        return self.status == STATUS_EXTRACTED

    def to_dict(self) -> dict:
        data = {
            "status": self.status,
            "kind": self.kind,
            "method": self.method,
            "extractor_version": EXTRACTOR_VERSION,
        }
        if self.detail:
            data["detail"] = self.detail
        if self.pages is not None:
            data["pages"] = self.pages
        return data


def extraction_kind(mime_type: str, filename: str, payload: Optional[bytes] = None) -> Optional[str]:
    """The extractor for a file, from its declared type, its name, then its bytes.

    Declared MIME types win. A generic type (``application/octet-stream``)
    falls back to the file extension, and when bytes are available, to their
    signature. Returns ``None`` for anything this module does not read.
    """
    mime = (mime_type or "").split(";", 1)[0].strip().casefold()
    suffix = Path(filename or "").suffix.casefold()
    if mime == PDF_MIME:
        return KIND_PDF
    if mime == DOCX_MIME:
        return KIND_DOCX
    if mime in MARKDOWN_MIME_TYPES:
        return KIND_MARKDOWN
    if mime in TEXT_MIME_TYPES:
        return KIND_MARKDOWN if suffix in {".md", ".markdown"} else KIND_TEXT
    if mime not in _GENERIC_MIME_TYPES:
        return None
    by_suffix = {
        ".pdf": KIND_PDF,
        ".docx": KIND_DOCX,
        ".md": KIND_MARKDOWN,
        ".markdown": KIND_MARKDOWN,
        ".txt": KIND_TEXT,
    }.get(suffix)
    if by_suffix:
        return by_suffix
    if payload is not None and payload.startswith(b"%PDF-"):
        return KIND_PDF
    return None


def extract_text(payload: bytes, *, mime_type: str = "", filename: str = "") -> Extraction:
    """Extract readable text from one payload. Never raises for bad input."""
    kind = extraction_kind(mime_type, filename, payload)
    if kind is None:
        return Extraction(STATUS_UNSUPPORTED, detail=f"no extractor for {mime_type or 'unknown type'}")
    if len(payload) > MAX_EXTRACT_BYTES:
        return Extraction(STATUS_TOO_LARGE, kind=kind, detail=f"{len(payload)} bytes exceeds {MAX_EXTRACT_BYTES}")
    if not payload:
        return Extraction(STATUS_EMPTY, kind=kind, detail="zero-byte file")
    try:
        if kind == KIND_PDF:
            return _extract_pdf(payload)
        if kind == KIND_DOCX:
            return _extract_docx(payload)
        return _extract_plain(payload, kind)
    except Exception as exc:  # noqa: BLE001 - a bad file is a result, not a crash
        return Extraction(STATUS_MALFORMED, kind=kind, detail=_short_error(exc))


def sanitize_extracted_text(value: str) -> str:
    """Make untrusted document text safe to embed in canonical Markdown."""
    value = (value or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n\n")
    value = re.sub(r"[\x00-\x08\x0b\x0e-\x1f\x7f]", "", value)
    value = value.replace("<", "&lt;").replace(">", "&gt;")
    # A line of dashes could close the frontmatter block in naive readers.
    value = re.sub(r"(?m)^(\s*)---+\s*$", r"\1- - -", value)
    value = "\n".join(line.rstrip() for line in value.split("\n"))
    value = re.sub(r"\n{4,}", "\n\n\n", value)
    return value.strip()


# ------------------------------------------------------------------ formats


def _extract_plain(payload: bytes, kind: str) -> Extraction:
    if b"\x00" in payload:
        return Extraction(STATUS_MALFORMED, kind=kind, detail="binary content in a text file")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = payload.decode(encoding)
        except UnicodeDecodeError:
            continue
        cleaned = sanitize_extracted_text(text)
        if not cleaned:
            return Extraction(STATUS_EMPTY, kind=kind, detail="no text")
        return Extraction(STATUS_EXTRACTED, kind=kind, text=cleaned, method=f"{kind}-decode:{encoding}")
    return Extraction(STATUS_MALFORMED, kind=kind, detail="undecodable text encoding")


def _extract_pdf(payload: bytes) -> Extraction:
    try:
        from pypdf import PdfReader
        from pypdf.errors import FileNotDecryptedError, PdfReadError
    except ImportError:
        return Extraction(STATUS_EXTRACTOR_UNAVAILABLE, kind=KIND_PDF, detail="pypdf is not installed")
    # pypdf logs every recoverable structural quirk; the outcome is reported
    # through the returned status instead.
    logging.getLogger("pypdf").setLevel(logging.ERROR)

    if not payload.lstrip()[:1024].startswith(b"%PDF-") and b"%PDF-" not in payload[:1024]:
        return Extraction(STATUS_MALFORMED, kind=KIND_PDF, detail="missing PDF header")
    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
        if reader.is_encrypted:
            # Many PDFs are encrypted only against editing, with an empty user
            # password. Anything else needs a password we do not have.
            try:
                unlocked = reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                return Extraction(STATUS_PASSWORD_PROTECTED, kind=KIND_PDF, detail=_short_error(exc))
            if not unlocked:
                return Extraction(STATUS_PASSWORD_PROTECTED, kind=KIND_PDF, detail="PDF requires a password")
        pages = list(reader.pages)
        texts = []
        for page in pages:
            texts.append((page.extract_text() or "").strip())
    except FileNotDecryptedError as exc:
        return Extraction(STATUS_PASSWORD_PROTECTED, kind=KIND_PDF, detail=_short_error(exc))
    except PdfReadError as exc:
        return Extraction(STATUS_MALFORMED, kind=KIND_PDF, detail=_short_error(exc))

    page_count = len(pages)
    usable = sum(len(re.findall(r"[A-Za-z0-9]", text)) for text in texts)
    if page_count == 0:
        return Extraction(STATUS_EMPTY, kind=KIND_PDF, detail="PDF has no pages", pages=0)
    if usable < MIN_USABLE_PDF_CHARACTERS:
        return Extraction(
            STATUS_REQUIRES_OCR,
            kind=KIND_PDF,
            detail=f"no usable embedded text on {page_count} page(s)",
            pages=page_count,
        )
    sections = []
    blank_pages = 0
    for number, text in enumerate(texts, 1):
        if not text:
            blank_pages += 1
            continue
        sections.append(f"### Page {number}\n\n{sanitize_extracted_text(text)}" if page_count > 1 else sanitize_extracted_text(text))
    detail = f"{blank_pages} of {page_count} page(s) had no embedded text" if blank_pages else ""
    return Extraction(
        STATUS_EXTRACTED,
        kind=KIND_PDF,
        text="\n\n".join(sections),
        method="pdf-text:pypdf",
        detail=detail,
        pages=page_count,
    )


def _extract_docx(payload: bytes) -> Extraction:
    if payload.startswith(_OLE_MAGIC):
        # An encrypted OOXML file is wrapped in an OLE compound document.
        return Extraction(STATUS_PASSWORD_PROTECTED, kind=KIND_DOCX, detail="encrypted or legacy compound document")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = set(archive.namelist())
            if "word/document.xml" not in names:
                return Extraction(STATUS_MALFORMED, kind=KIND_DOCX, detail="missing word/document.xml")
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_EXTRACT_BYTES:
                return Extraction(STATUS_TOO_LARGE, kind=KIND_DOCX, detail="document.xml exceeds size limit")
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    except zipfile.BadZipFile as exc:
        return Extraction(STATUS_MALFORMED, kind=KIND_DOCX, detail=_short_error(exc))

    lines = [_docx_paragraph_text(paragraph) for paragraph in re.findall(r"<w:p\b[\s\S]*?</w:p>", xml)]
    text = sanitize_extracted_text("\n\n".join(line for line in lines if line))
    if not text:
        return Extraction(STATUS_EMPTY, kind=KIND_DOCX, detail="no text in document body")
    return Extraction(STATUS_EXTRACTED, kind=KIND_DOCX, text=text, method="docx-text:document.xml")


def _docx_paragraph_text(paragraph: str) -> str:
    # Regex over the XML on purpose: no entity expansion, no parser surprises
    # from untrusted input. Tabs and breaks become whitespace so words that
    # sit either side of them stay apart.
    paragraph = re.sub(r"<w:tab\s*/>", "<w:t>\t</w:t>", paragraph)
    paragraph = re.sub(r"<w:(?:br|cr)\b[^>]*/>", "<w:t>\n</w:t>", paragraph)
    parts = re.findall(r"<w:t(?:\s[^>]*)?>([\s\S]*?)</w:t>", paragraph)
    text = html.unescape("".join(parts))
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def _short_error(exc: Exception) -> str:
    return re.sub(r"\s+", " ", str(exc)).strip()[:200] or exc.__class__.__name__
