"""Tiny, dependency-free builders for real PDF and DOCX test payloads."""

import io
import zipfile
from xml.sax.saxutils import escape


def text_pdf(lines, *, pages=None):
    """A valid PDF whose pages carry an embedded Helvetica text layer.

    ``pages`` is a list of line lists; ``lines`` alone makes one page.
    """
    page_lines = pages if pages is not None else [lines]
    streams = []
    for lines_on_page in page_lines:
        commands = ["BT", "/F1 12 Tf", "72 720 Td", "14 TL"]
        for line in lines_on_page:
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({safe}) Tj T*")
        commands.append("ET")
        streams.append("\n".join(commands).encode("latin-1"))
    return _pdf(streams, font=True)


def blank_pdf(pages=1):
    """A valid PDF with no text layer, like a scan."""
    return _pdf([b"0 0 m 100 100 l S" for _ in range(pages)], font=False)


def encrypted_pdf(lines, *, password="secret"):
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(text_pdf(lines))).pages:
        writer.add_page(page)
    writer.encrypt(user_password=password, owner_password=password + "-owner", algorithm="RC4-128")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def docx(paragraphs):
    """A minimal valid DOCX with one ``w:p`` per paragraph."""
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{escape(paragraph)}</w:t></w:r></w:p>' for paragraph in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def _pdf(streams, *, font):
    objects = []
    page_count = len(streams)
    first_page = 3
    font_object = first_page + 2 * page_count
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{first_page + 2 * index} 0 R" for index in range(page_count))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode())
    for index, stream in enumerate(streams):
        content_ref = first_page + 2 * index + 1
        resources = f"/Resources << /Font << /F1 {font_object} 0 R >> >>" if font else "/Resources << >>"
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] {resources} /Contents {content_ref} 0 R >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    if font:
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(output.tell())
        output.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        output.write(f"{offset:010d} 00000 n \n".encode())
    output.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return output.getvalue()
