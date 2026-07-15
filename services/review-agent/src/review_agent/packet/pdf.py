"""Deterministic, dependency-free PDF rendering for evidence packets (FR-6).

The reviewer-approved packet is rendered to a real PDF using only the standard
library so the local slice and CI stay dependency-free and the same bytes are
produced on AWS. The document embeds every packet section and its material
citations as visible text (the content stream is left uncompressed so citations
are inspectable). The bytes always begin with the ``%PDF-`` signature.

The model never writes policy text here; this module only lays out packet
content that the deterministic composer already produced.
"""

from __future__ import annotations

from ..contracts.packet import Packet

_PAGE_WIDTH = 612
_PAGE_HEIGHT = 792
_LEFT_MARGIN = 54
_TOP = 748
_LINE_HEIGHT = 15
_FONT_SIZE = 11
_WRAP = 92
_LINES_PER_PAGE = int((_TOP - 54) / _LINE_HEIGHT)


def _wrap(text: str, width: int = _WRAP) -> list[str]:
    lines: list[str] = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        if not raw_line:
            lines.append("")
            continue
        current = ""
        for word in raw_line.split(" "):
            candidate = word if not current else f"{current} {word}"
            if len(candidate) <= width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                # Hard-split words longer than the wrap width.
                while len(word) > width:
                    lines.append(word[:width])
                    word = word[width:]
                current = word
        lines.append(current)
    return lines


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _packet_lines(packet: Packet, *, title: str) -> list[str]:
    lines: list[str] = []
    lines.append(title)
    lines.append("")
    lines.append(f"Case: {packet.case_id}")
    lines.append(f"Packet: {packet.packet_id}  v{packet.packet_version}  ({packet.packet_type.value})")
    if packet.sha256:
        lines.append(f"Content SHA-256: {packet.sha256}")
    lines.append("")
    for section in packet.sections:
        lines.append(f"## {section.title}")
        for wrapped in _wrap(section.body):
            lines.append(wrapped)
        if section.citations:
            lines.append("Citations:")
            for citation in section.citations:
                lines.extend(_wrap(f"  - {_citation_text(citation)}"))
        lines.append("")
    material = packet.citations
    lines.append("## Material citations")
    if material:
        for citation in material:
            lines.extend(_wrap(f"  - {_citation_text(citation)}"))
    else:
        lines.append("  (none recorded)")
    if packet.unsupported_claims:
        lines.append("")
        lines.append("## Unsupported claims (dropped)")
        for claim in packet.unsupported_claims:
            lines.extend(_wrap(f"  - {claim}"))
    return lines


def _citation_text(citation) -> str:
    if hasattr(citation, "to_dict"):
        data = citation.to_dict()
    elif isinstance(citation, dict):
        data = citation
    else:  # pragma: no cover - defensive
        return str(citation)
    source = data.get("source", {}) or {}
    source_id = source.get("source_id", "unknown-source")
    claim = data.get("claim", "")
    return f"{claim} [{source_id}]" if claim else f"[{source_id}]"


def _content_stream(lines: list[str]) -> bytes:
    parts = ["BT", f"/F1 {_FONT_SIZE} Tf", f"{_LINE_HEIGHT} TL", f"{_LEFT_MARGIN} {_TOP} Td"]
    first = True
    for line in lines:
        if first:
            parts.append(f"({_escape(line)}) Tj")
            first = False
        else:
            parts.append(f"T* ({_escape(line)}) Tj")
    parts.append("ET")
    return ("\n".join(parts) + "\n").encode("latin-1", errors="replace")


def render_packet_pdf(packet: Packet, *, title: str = "VETTED Evidence Packet") -> bytes:
    """Render ``packet`` to a valid, deterministic single-font PDF byte string."""
    all_lines = _packet_lines(packet, title=title)
    pages = [
        all_lines[i : i + _LINES_PER_PAGE] for i in range(0, len(all_lines), _LINES_PER_PAGE)
    ] or [[""]]

    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []
    pages_parent_id = len(objects) + 1 + 2 * len(pages)  # reserve slot for Pages object
    for page_lines in pages:
        stream = _content_stream(page_lines)
        content_id = add(
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream"
        )
        page_id = add(
            (
                f"<< /Type /Page /Parent {pages_parent_id} 0 R "
                f"/MediaBox [0 0 {_PAGE_WIDTH} {_PAGE_HEIGHT}] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
        page_ids.append(page_id)
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    pages_id = add(
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")
    )
    assert pages_id == pages_parent_id, "pages object id must match reserved parent id"
    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii"))

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_offset = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {count} /Root {catalog_id} 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
    ).encode("ascii")
    return bytes(out)
