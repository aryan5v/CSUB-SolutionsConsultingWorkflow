"""Bounded evidence-byte validation and document-specific extraction routes."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Protocol, runtime_checkable
from zipfile import BadZipFile, ZipFile

from ..institutional.untrusted import scan_untrusted_text
from .ingestion import (
    MAX_EVIDENCE_BYTES,
    MANUAL_REVIEW_CONTENT_TYPES,
    EvidenceStateStore,
    EvidenceUploadRecord,
    ProcessingState,
    extraction_event_id,
    extraction_key,
)

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MSG_MIMES = frozenset({"application/vnd.ms-outlook", "application/x-msg"})
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_PDF_PAGE_OBJECT = re.compile(rb"/Type\s*/Page(?!s)\b")
_PDF_PAGE_COUNT = re.compile(rb"/Count\s+([0-9]+)\b")
_OLE_FREE_SECTOR = 0xFFFFFFFF
_OLE_END_OF_CHAIN = 0xFFFFFFFE
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_CELL_REF = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")
_MAX_ARCHIVE_ENTRIES = 2_000
_MAX_ARCHIVE_EXPANDED_BYTES = 20_000_000
_MAX_CHUNK_CHARS = 20_000
_EXECUTABLE_MAGIC = (
    b"MZ",
    b"\x7fELF",
    b"\xcf\xfa\xed\xfe",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xfe\xed\xfa\xce",
)
_ACTIVE_SUFFIXES = (".exe", ".dll", ".com", ".bat", ".cmd", ".js", ".vbs", ".ps1")


class EvidenceProcessingError(RuntimeError):
    def __init__(self, code: str, message: str, *, manual_review: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.manual_review = manual_review


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    content_length: int
    content_type: str
    version_id: str | None
    checksum_sha256: str | None
    metadata: dict[str, str]


@runtime_checkable
class EvidenceObjectStore(Protocol):
    def head(self, *, key: str) -> ObjectMetadata: ...

    def read(self, *, key: str, max_bytes: int) -> bytes: ...

    def write_extraction(
        self, *, key: str, payload: dict[str, Any], source_sha256: str
    ) -> None: ...


class InMemoryEvidenceObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, ObjectMetadata]] = {}
        self.extractions: dict[str, dict[str, Any]] = {}
        self.extraction_writes = 0

    def put_source(
        self,
        *,
        key: str,
        body: bytes,
        content_type: str,
        metadata: dict[str, str],
        version_id: str = "version-1",
    ) -> None:
        import base64

        self.objects[key] = (
            body,
            ObjectMetadata(
                content_length=len(body),
                content_type=content_type,
                version_id=version_id,
                checksum_sha256=base64.b64encode(hashlib.sha256(body).digest()).decode("ascii"),
                metadata=dict(metadata),
            ),
        )

    def head(self, *, key: str) -> ObjectMetadata:
        if key not in self.objects:
            raise EvidenceProcessingError("interrupted_upload", "quarantine object is absent")
        return self.objects[key][1]

    def read(self, *, key: str, max_bytes: int) -> bytes:
        if key not in self.objects:
            raise EvidenceProcessingError("interrupted_upload", "quarantine object is absent")
        body = self.objects[key][0]
        if len(body) > max_bytes:
            raise EvidenceProcessingError("oversized", "quarantine object exceeds processing limit")
        return body

    def write_extraction(
        self, *, key: str, payload: dict[str, Any], source_sha256: str
    ) -> None:
        if payload.get("source_sha256") != source_sha256:
            raise ValueError("extraction provenance hash does not match source")
        if key not in self.extractions:
            self.extractions[key] = json.loads(json.dumps(payload))
            self.extraction_writes += 1


class S3EvidenceObjectStore:
    """S3 adapter that closes streams and writes only sanitized extraction JSON."""

    def __init__(self, *, bucket: str, client: Any, kms_key_id: str | None = None) -> None:
        self._bucket = bucket
        self._client = client
        self._kms_key_id = kms_key_id

    def head(self, *, key: str) -> ObjectMetadata:
        response = self._client.head_object(Bucket=self._bucket, Key=key, ChecksumMode="ENABLED")
        return ObjectMetadata(
            content_length=int(response.get("ContentLength", -1)),
            content_type=str(response.get("ContentType") or "application/octet-stream"),
            version_id=response.get("VersionId"),
            checksum_sha256=response.get("ChecksumSHA256"),
            metadata={str(k): str(v) for k, v in response.get("Metadata", {}).items()},
        )

    def read(self, *, key: str, max_bytes: int) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        body = response["Body"]
        try:
            payload = body.read(max_bytes + 1)
        finally:
            body.close()
        if len(payload) > max_bytes:
            raise EvidenceProcessingError("oversized", "quarantine object exceeds processing limit")
        return payload

    def write_extraction(
        self, *, key: str, payload: dict[str, Any], source_sha256: str
    ) -> None:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": encoded,
            "ContentType": "application/json",
            "Metadata": {"source-sha256": source_sha256, "untrusted": "true"},
            "ServerSideEncryption": "aws:kms",
            "IfNoneMatch": "*",
        }
        if self._kms_key_id:
            params["SSEKMSKeyId"] = self._kms_key_id
        try:
            self._client.put_object(**params)
        except Exception as error:
            response = getattr(error, "response", None)
            details = response.get("Error") if isinstance(response, dict) else None
            code = details.get("Code") if isinstance(details, dict) else None
            if code not in {"PreconditionFailed", "ConditionalRequestConflict"}:
                raise
            existing = self._client.head_object(Bucket=self._bucket, Key=key)
            metadata = existing.get("Metadata", {})
            if metadata.get("source-sha256") != source_sha256:
                raise EvidenceProcessingError(
                    "extraction_conflict",
                    "existing extraction has different source provenance",
                ) from error


@runtime_checkable
class TextractAdapter(Protocol):
    def lines(
        self, *, record: EvidenceUploadRecord, source_version_id: str | None
    ) -> list[dict[str, Any]]: ...


class FakeTextractAdapter:
    def __init__(self, lines: list[dict[str, Any]] | None = None) -> None:
        self._lines = list(lines or [])
        self.calls = 0

    def lines(
        self, *, record: EvidenceUploadRecord, source_version_id: str | None
    ) -> list[dict[str, Any]]:
        del record, source_version_id
        self.calls += 1
        return json.loads(json.dumps(self._lines))


class AwsTextractAdapter:
    def __init__(self, *, bucket: str, client: Any) -> None:
        self._bucket = bucket
        self._client = client

    def lines(
        self, *, record: EvidenceUploadRecord, source_version_id: str | None
    ) -> list[dict[str, Any]]:
        source = {"Bucket": self._bucket, "Name": record.object_key}
        if source_version_id:
            source["Version"] = source_version_id
        response = self._client.detect_document_text(Document={"S3Object": source})
        lines: list[dict[str, Any]] = []
        current_page = 1
        for block in response.get("Blocks", []):
            if not isinstance(block, dict):
                continue
            if block.get("BlockType") == "PAGE":
                current_page = int(block.get("Page", current_page))
            if block.get("BlockType") != "LINE" or not isinstance(block.get("Text"), str):
                continue
            geometry = block.get("Geometry") if isinstance(block.get("Geometry"), dict) else {}
            box = geometry.get("BoundingBox") if isinstance(geometry.get("BoundingBox"), dict) else {}
            lines.append(
                {
                    "text": block["Text"],
                    "page": int(block.get("Page", current_page)),
                    "region": {
                        key.lower(): float(box[key])
                        for key in ("Left", "Top", "Width", "Height")
                        if key in box
                    },
                }
            )
        return lines


class EvidenceProcessor:
    """Idempotent validator/extractor over one immutable quarantine object."""

    def __init__(
        self,
        *,
        state_store: EvidenceStateStore,
        object_store: EvidenceObjectStore,
        textract: TextractAdapter,
        lease_seconds: int = 120,
    ) -> None:
        self._state = state_store
        self._objects = object_store
        self._textract = textract
        self._lease_seconds = lease_seconds

    def process(self, record: EvidenceUploadRecord) -> EvidenceUploadRecord:
        now_epoch = int(time.time())
        claim_token = self._state.claim(
            record, now_epoch=now_epoch, lease_seconds=self._lease_seconds
        )
        if claim_token is None:
            current = self._state.get(
                workspace_id=record.workspace_id,
                case_id=record.case_id,
                artifact_id=record.artifact_id,
            )
            if current is None:
                raise EvidenceProcessingError("unregistered", "evidence is not registered")
            return current
        warnings: list[str] = []
        source_version_id: str | None = None
        detected_content_type: str | None = None
        try:
            metadata = self._objects.head(key=record.object_key)
            source_version_id = metadata.version_id
            _validate_object_metadata(record, metadata)
            body = self._objects.read(key=record.object_key, max_bytes=MAX_EVIDENCE_BYTES)
            _validate_source_hash(record, body, metadata)
            detected_content_type = detect_content_type(body, record.declared_content_type)
            if detected_content_type != record.declared_content_type:
                raise EvidenceProcessingError(
                    "mime_mismatch",
                    "declared content type does not match the object signature",
                )
            chunks, route_warnings = self._extract(
                record=record,
                body=body,
                detected_content_type=detected_content_type,
                source_version_id=source_version_id,
            )
            for chunk in chunks:
                chunk["source_version_id"] = source_version_id
                chunk["source_object_key"] = record.object_key
            warnings.extend(route_warnings)
            output_key = extraction_key(record)
            payload = {
                "schema_version": 1,
                "workspace_id": record.workspace_id,
                "case_id": record.case_id,
                "product_id": record.product_id,
                "vendor_id": record.vendor_id,
                "artifact_id": record.artifact_id,
                "source_sha256": record.source_sha256,
                "source_object_key": record.object_key,
                "source_version_id": source_version_id,
                "declared_content_type": record.declared_content_type,
                "detected_content_type": detected_content_type,
                "untrusted": True,
                "model_use_allowed": False,
                "warnings": warnings,
                "chunks": chunks,
            }
            _validate_extraction_payload(payload)
            self._objects.write_extraction(
                key=output_key,
                payload=payload,
                source_sha256=record.source_sha256,
            )
            return self._state.complete(
                record,
                claim_token=claim_token,
                state=ProcessingState.READY,
                source_version_id=source_version_id,
                detected_content_type=detected_content_type,
                extraction_key=output_key,
                warnings=tuple(warnings),
                failure_code=None,
                extraction_event_id=extraction_event_id(record),
            )
        except EvidenceProcessingError as error:
            return self._state.complete(
                record,
                claim_token=claim_token,
                state=(
                    ProcessingState.MANUAL_REVIEW
                    if error.manual_review
                    else ProcessingState.FAILED
                ),
                source_version_id=source_version_id,
                detected_content_type=detected_content_type,
                extraction_key=None,
                warnings=tuple([*warnings, str(error)]),
                failure_code=error.code,
                extraction_event_id=None,
            )
        except Exception:
            self._state.complete(
                record,
                claim_token=claim_token,
                state=ProcessingState.FAILED,
                source_version_id=source_version_id,
                detected_content_type=detected_content_type,
                extraction_key=None,
                warnings=tuple(warnings),
                failure_code="processing_error",
                extraction_event_id=None,
            )
            raise

    def _extract(
        self,
        *,
        record: EvidenceUploadRecord,
        body: bytes,
        detected_content_type: str,
        source_version_id: str | None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        if detected_content_type in {"application/pdf", "image/png", "image/jpeg"}:
            if detected_content_type == "application/pdf" and b"/Encrypt" in body:
                raise EvidenceProcessingError(
                    "encrypted_document",
                    "encrypted PDF requires manual review",
                    manual_review=True,
                )
            _validate_synchronous_textract_input(body, detected_content_type)
            lines = self._textract.lines(
                record=record,
                source_version_id=source_version_id,
            )
            chunks = []
            warnings: list[str] = []
            for index, line in enumerate(lines, start=1):
                text = line.get("text")
                if not isinstance(text, str):
                    continue
                chunk, findings = _chunk(
                    record,
                    raw_value=text,
                    coordinates={
                        "page": int(line.get("page", 1)),
                        "region": line.get("region", {}),
                    },
                    ordinal=index,
                )
                chunks.append(chunk)
                warnings.extend(findings)
            if not chunks:
                raise EvidenceProcessingError(
                    "no_extractable_text",
                    "document contains no extractable text",
                    manual_review=True,
                )
            return chunks, _dedupe(warnings)
        if detected_content_type == _DOCX_MIME:
            return _extract_docx(record, body)
        if detected_content_type == _XLSX_MIME:
            return _extract_xlsx(record, body)
        if detected_content_type == "text/csv":
            return _extract_csv(record, body)
        if detected_content_type == "text/plain":
            return _extract_text(record, body)
        raise EvidenceProcessingError(
            "unsupported_type", "document type requires manual review", manual_review=True
        )


def detect_content_type(body: bytes, declared_content_type: str) -> str:
    if not body:
        raise EvidenceProcessingError("empty_upload", "empty evidence upload")
    if any(body.startswith(magic) for magic in _EXECUTABLE_MAGIC):
        raise EvidenceProcessingError("executable", "executable evidence is rejected")
    if body.startswith(b"%PDF-"):
        eof = body.rfind(b"%%EOF")
        if eof < 0:
            raise EvidenceProcessingError("malformed", "PDF end marker is missing")
        trailing = body[eof + 5 :].strip()
        if trailing:
            raise EvidenceProcessingError("polyglot", "polyglot PDF is rejected")
        return "application/pdf"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        end = body.rfind(b"IEND\xaeB`\x82")
        if end < 0:
            raise EvidenceProcessingError("malformed", "PNG end marker is missing")
        if body[end + 8 :].strip():
            raise EvidenceProcessingError("polyglot", "polyglot PNG is rejected")
        return "image/png"
    if body.startswith(b"\xff\xd8\xff"):
        end = body.rfind(b"\xff\xd9")
        if end < 0:
            raise EvidenceProcessingError("malformed", "JPEG end marker is missing")
        if body[end + 2 :].strip():
            raise EvidenceProcessingError("polyglot", "polyglot JPEG is rejected")
        return "image/jpeg"
    if body.startswith(_OLE_SIGNATURE):
        _validate_ole_container(body)
        if declared_content_type in _MSG_MIMES or declared_content_type == "application/octet-stream":
            return declared_content_type
        raise EvidenceProcessingError("mime_mismatch", "OLE evidence does not match its declared type")
    if body.startswith(b"{\\rtf"):
        if declared_content_type == "application/rtf":
            return declared_content_type
        raise EvidenceProcessingError("mime_mismatch", "RTF evidence does not match its declared type")
    if body.startswith(b"PK\x03\x04"):
        names = _validate_archive(body)
        if "word/document.xml" in names:
            return _DOCX_MIME
        if "xl/workbook.xml" in names:
            return _XLSX_MIME
        raise EvidenceProcessingError("archive", "archives are not accepted as evidence")
    if declared_content_type in MANUAL_REVIEW_CONTENT_TYPES:
        raise EvidenceProcessingError(
            "unsupported_type",
            "unsupported evidence is retained for manual review",
            manual_review=True,
        )
    if b"\x00" in body:
        raise EvidenceProcessingError("binary", "binary evidence type is unsupported")
    try:
        body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvidenceProcessingError("invalid_text_encoding", "text evidence must be UTF-8") from error
    if declared_content_type in {"text/plain", "text/csv"}:
        return declared_content_type
    raise EvidenceProcessingError("mime_mismatch", "object signature does not match declared type")


def _validate_synchronous_textract_input(body: bytes, content_type: str) -> None:
    """Reject inputs outside the bounded synchronous DetectDocumentText surface."""
    if len(body) > MAX_EVIDENCE_BYTES:
        raise EvidenceProcessingError("oversized", "document exceeds the synchronous extraction limit")
    if content_type != "application/pdf":
        return
    page_objects = len(_PDF_PAGE_OBJECT.findall(body))
    declared_counts = [int(value) for value in _PDF_PAGE_COUNT.findall(body)]
    page_count = max([page_objects, *declared_counts], default=0)
    if page_count > 1:
        raise EvidenceProcessingError(
            "textract_async_required",
            "multi-page PDF requires a bounded asynchronous extraction workflow",
            manual_review=True,
        )


def _validate_ole_container(body: bytes) -> None:
    """Validate the fixed OLE/CFBF header before retaining a .msg for manual review."""
    if len(body) < 1024 or (len(body) - 512) % 512 != 0:
        raise EvidenceProcessingError("malformed", "OLE compound document length is invalid")
    if body[:8] != _OLE_SIGNATURE or body[8:24] != b"\x00" * 16:
        raise EvidenceProcessingError("malformed", "OLE compound document header is invalid")
    major_version = int.from_bytes(body[26:28], "little")
    byte_order = int.from_bytes(body[28:30], "little")
    sector_shift = int.from_bytes(body[30:32], "little")
    mini_sector_shift = int.from_bytes(body[32:34], "little")
    if byte_order != 0xFFFE or major_version not in {3, 4}:
        raise EvidenceProcessingError("malformed", "OLE compound document format is unsupported")
    if sector_shift != (9 if major_version == 3 else 12) or mini_sector_shift != 6:
        raise EvidenceProcessingError("malformed", "OLE compound document sector sizes are invalid")
    if body[34:40] != b"\x00" * 6 or int.from_bytes(body[56:60], "little") != 4096:
        raise EvidenceProcessingError("malformed", "OLE compound document reserved fields are invalid")
    sector_size = 1 << sector_shift
    if (len(body) - 512) % sector_size != 0:
        raise EvidenceProcessingError("malformed", "OLE compound document is not sector aligned")
    sector_count = (len(body) - 512) // sector_size
    fat_sector_count = int.from_bytes(body[44:48], "little")
    first_directory_sector = int.from_bytes(body[48:52], "little")
    first_difat_sector = int.from_bytes(body[68:72], "little")
    difat_sector_count = int.from_bytes(body[72:76], "little")
    if fat_sector_count > sector_count or first_directory_sector >= sector_count:
        raise EvidenceProcessingError("malformed", "OLE compound document sector references are invalid")
    if difat_sector_count > sector_count or (
        difat_sector_count == 0 and first_difat_sector not in {_OLE_FREE_SECTOR, _OLE_END_OF_CHAIN}
    ):
        raise EvidenceProcessingError("malformed", "OLE compound document DIFAT is invalid")


def _validate_object_metadata(record: EvidenceUploadRecord, metadata: ObjectMetadata) -> None:
    if metadata.content_length != record.expected_size_bytes:
        raise EvidenceProcessingError("size_mismatch", "uploaded size differs from registration")
    if metadata.content_length < 1 or metadata.content_length > MAX_EVIDENCE_BYTES:
        raise EvidenceProcessingError("oversized", "uploaded object exceeds the evidence limit")
    if metadata.content_type != record.declared_content_type:
        raise EvidenceProcessingError("mime_mismatch", "uploaded Content-Type differs from registration")
    expected = {
        "workspace-id": record.workspace_id,
        "case-id": record.case_id,
        "product-id": record.product_id,
        "artifact-id": record.artifact_id,
        "source-sha256": record.source_sha256,
    }
    if any(metadata.metadata.get(key) != value for key, value in expected.items()):
        raise EvidenceProcessingError("scope_mismatch", "uploaded object metadata is not case-scoped")


def _validate_source_hash(
    record: EvidenceUploadRecord, body: bytes, metadata: ObjectMetadata
) -> None:
    import base64

    actual = hashlib.sha256(body).hexdigest()
    if actual != record.source_sha256:
        raise EvidenceProcessingError("hash_mismatch", "uploaded bytes do not match registered sha256")
    if metadata.checksum_sha256:
        expected_checksum = base64.b64encode(bytes.fromhex(record.source_sha256)).decode("ascii")
        if metadata.checksum_sha256 != expected_checksum:
            raise EvidenceProcessingError("checksum_mismatch", "S3 checksum does not match registration")


def _validate_archive(body: bytes) -> set[str]:
    try:
        with ZipFile(io.BytesIO(body)) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_ARCHIVE_ENTRIES:
                raise EvidenceProcessingError("archive_limit", "document container has too many entries")
            expanded = 0
            names: set[str] = set()
            for info in infos:
                path = PurePosixPath(info.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise EvidenceProcessingError("archive_path", "document container path is unsafe")
                lowered = info.filename.lower()
                if lowered.endswith(_ACTIVE_SUFFIXES) or "vbaproject.bin" in lowered:
                    raise EvidenceProcessingError("active_content", "active document content is rejected")
                expanded += info.file_size
                if expanded > _MAX_ARCHIVE_EXPANDED_BYTES:
                    raise EvidenceProcessingError("archive_limit", "expanded document exceeds limit")
                names.add(info.filename)
            return names
    except BadZipFile as error:
        raise EvidenceProcessingError("malformed", "document container is malformed") from error


def _extract_text(
    record: EvidenceUploadRecord, body: bytes
) -> tuple[list[dict[str, Any]], list[str]]:
    text = body.decode("utf-8")
    chunks: list[dict[str, Any]] = []
    warnings: list[str] = []
    for line_number, raw in enumerate(text.splitlines(), start=1):
        chunk, findings = _chunk(
            record,
            raw_value=raw,
            coordinates={"line": line_number},
            ordinal=line_number,
        )
        chunks.append(chunk)
        warnings.extend(findings)
    if not chunks:
        chunk, findings = _chunk(record, raw_value="", coordinates={"line": 1}, ordinal=1)
        chunks.append(chunk)
        warnings.extend(findings)
    return chunks, _dedupe(warnings)


def _extract_csv(
    record: EvidenceUploadRecord, body: bytes
) -> tuple[list[dict[str, Any]], list[str]]:
    text = body.decode("utf-8")
    chunks: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        rows = csv.reader(io.StringIO(text, newline=""), strict=True)
        ordinal = 0
        for row_number, row in enumerate(rows, start=1):
            for column_number, raw in enumerate(row, start=1):
                ordinal += 1
                chunk, findings = _chunk(
                    record,
                    raw_value=raw,
                    coordinates={
                        "row": row_number,
                        "column": _column_name(column_number),
                        "cell": f"{_column_name(column_number)}{row_number}",
                    },
                    ordinal=ordinal,
                )
                chunks.append(chunk)
                warnings.extend(findings)
    except csv.Error as error:
        raise EvidenceProcessingError("malformed", "CSV evidence is malformed") from error
    return chunks, _dedupe(warnings)


def _extract_docx(
    record: EvidenceUploadRecord, body: bytes
) -> tuple[list[dict[str, Any]], list[str]]:
    _validate_archive(body)
    try:
        with ZipFile(io.BytesIO(body)) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
    except (BadZipFile, KeyError, ET.ParseError) as error:
        raise EvidenceProcessingError("malformed", "DOCX evidence is malformed") from error
    chunks: list[dict[str, Any]] = []
    warnings: list[str] = []
    for ordinal, paragraph in enumerate(root.iter(f"{{{_WORD_NS}}}p"), start=1):
        raw = "".join(node.text or "" for node in paragraph.iter(f"{{{_WORD_NS}}}t"))
        chunk, findings = _chunk(
            record,
            raw_value=raw,
            coordinates={"paragraph": ordinal},
            ordinal=ordinal,
        )
        chunks.append(chunk)
        warnings.extend(findings)
    if not chunks:
        raise EvidenceProcessingError("no_extractable_text", "DOCX contains no paragraphs", manual_review=True)
    return chunks, _dedupe(warnings)


def _extract_xlsx(
    record: EvidenceUploadRecord, body: bytes
) -> tuple[list[dict[str, Any]], list[str]]:
    _validate_archive(body)
    chunks: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        with ZipFile(io.BytesIO(body)) as archive:
            shared = _xlsx_shared_strings(archive)
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            targets = {
                item.attrib["Id"]: item.attrib["Target"]
                for item in relationships.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
            }
            sheets = workbook.find(f"{{{_MAIN_NS}}}sheets")
            if sheets is None:
                raise EvidenceProcessingError("malformed", "XLSX has no sheets")
            ordinal = 0
            for sheet in list(sheets):
                sheet_name = sheet.attrib.get("name", "Sheet")
                relationship_id = sheet.attrib.get(f"{{{_REL_NS}}}id")
                target = targets.get(str(relationship_id), "").lstrip("/")
                if not target.startswith("xl/"):
                    target = f"xl/{target}"
                if not target or ".." in PurePosixPath(target).parts:
                    raise EvidenceProcessingError("archive_path", "worksheet relationship is unsafe")
                worksheet = ET.fromstring(archive.read(target))
                merged = worksheet.find(f"{{{_MAIN_NS}}}mergeCells")
                if merged is not None:
                    for cell_range in merged.findall(f"{{{_MAIN_NS}}}mergeCell"):
                        warnings.append(
                            f"merged cells preserved on {sheet_name}: {cell_range.attrib.get('ref', 'unknown')}"
                        )
                for cell in worksheet.iter(f"{{{_MAIN_NS}}}c"):
                    reference = cell.attrib.get("r", "")
                    match = _CELL_REF.fullmatch(reference)
                    if match is None:
                        raise EvidenceProcessingError("malformed", "XLSX cell reference is invalid")
                    raw, formula = _xlsx_cell_value(cell, shared)
                    ordinal += 1
                    chunk, findings = _chunk(
                        record,
                        raw_value=raw,
                        coordinates={
                            "sheet": sheet_name,
                            "cell": reference,
                            "row": int(match.group(2)),
                            "column": match.group(1),
                        },
                        ordinal=ordinal,
                        formula=formula,
                    )
                    chunks.append(chunk)
                    warnings.extend(findings)
                    if formula is not None:
                        warnings.append(f"formula preserved from {sheet_name}!{reference}")
    except EvidenceProcessingError:
        raise
    except (BadZipFile, KeyError, IndexError, ValueError, ET.ParseError) as error:
        raise EvidenceProcessingError("malformed", "XLSX evidence is malformed") from error
    if not chunks:
        raise EvidenceProcessingError("no_extractable_text", "XLSX contains no cells", manual_review=True)
    return chunks, _dedupe(warnings)


def _xlsx_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t"))
        for item in root.findall(f"{{{_MAIN_NS}}}si")
    ]


def _xlsx_cell_value(cell: ET.Element, shared: list[str]) -> tuple[str, str | None]:
    formula_node = cell.find(f"{{{_MAIN_NS}}}f")
    formula = None if formula_node is None else f"={formula_node.text or ''}"
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        raw = "".join(node.text or "" for node in cell.iter(f"{{{_MAIN_NS}}}t"))
    else:
        value_node = cell.find(f"{{{_MAIN_NS}}}v")
        raw = "" if value_node is None or value_node.text is None else value_node.text
        if cell_type == "s" and raw:
            raw = shared[int(raw)]
    return raw, formula


def _chunk(
    record: EvidenceUploadRecord,
    *,
    raw_value: str,
    coordinates: dict[str, Any],
    ordinal: int,
    formula: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    sanitized = "".join(
        character
        for character in raw_value
        if character in "\t\n\r" or (ord(character) >= 32 and ord(character) != 127)
    )
    warnings: list[str] = []
    if sanitized != raw_value:
        warnings.append(f"control characters removed at source ordinal {ordinal}")
    if len(sanitized) > _MAX_CHUNK_CHARS:
        sanitized = sanitized[:_MAX_CHUNK_CHARS]
        warnings.append(f"chunk truncated at source ordinal {ordinal}")
    for finding in scan_untrusted_text(sanitized):
        warnings.append(f"{finding.kind} at source ordinal {ordinal}: {finding.detail}")
    chunk_id = hashlib.sha256(
        f"{record.source_sha256}:{ordinal}:{json.dumps(coordinates, sort_keys=True)}".encode("utf-8")
    ).hexdigest()
    return (
        {
            "chunk_id": chunk_id,
            "text": sanitized,
            "raw_value": raw_value,
            "formula": formula,
            "coordinates": coordinates,
            "source_sha256": record.source_sha256,
            "source_version_id": None,
            "untrusted": True,
            "model_use_allowed": False,
        },
        warnings,
    )


def _validate_extraction_payload(payload: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "workspace_id",
        "case_id",
        "product_id",
        "vendor_id",
        "artifact_id",
        "source_sha256",
        "source_object_key",
        "source_version_id",
        "declared_content_type",
        "detected_content_type",
        "untrusted",
        "model_use_allowed",
        "warnings",
        "chunks",
    }
    if set(payload) != required or payload.get("schema_version") != 1:
        raise EvidenceProcessingError("invalid_extraction", "extraction envelope is invalid")
    if payload.get("untrusted") is not True or payload.get("model_use_allowed") is not False:
        raise EvidenceProcessingError("invalid_extraction", "extraction trust flags are invalid")
    warnings = payload.get("warnings")
    chunks = payload.get("chunks")
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        raise EvidenceProcessingError("invalid_extraction", "extraction warnings are invalid")
    if not isinstance(chunks, list):
        raise EvidenceProcessingError("invalid_extraction", "extraction chunks are invalid")
    chunk_keys = {
        "chunk_id",
        "text",
        "raw_value",
        "formula",
        "coordinates",
        "source_sha256",
        "source_version_id",
        "source_object_key",
        "untrusted",
        "model_use_allowed",
    }
    coordinate_keys = {
        "page",
        "sheet",
        "cell",
        "row",
        "column",
        "line",
        "paragraph",
        "region",
    }
    for chunk in chunks:
        if not isinstance(chunk, dict) or set(chunk) != chunk_keys:
            raise EvidenceProcessingError("invalid_extraction", "extraction chunk shape is invalid")
        if not all(
            isinstance(chunk[key], str)
            for key in ("chunk_id", "text", "raw_value", "source_sha256", "source_object_key")
        ):
            raise EvidenceProcessingError("invalid_extraction", "extraction chunk text is invalid")
        if chunk["formula"] is not None and not isinstance(chunk["formula"], str):
            raise EvidenceProcessingError("invalid_extraction", "extraction formula is invalid")
        coordinates = chunk["coordinates"]
        if not isinstance(coordinates, dict) or set(coordinates) - coordinate_keys:
            raise EvidenceProcessingError("invalid_extraction", "extraction coordinates are invalid")
        if (
            chunk["source_sha256"] != payload["source_sha256"]
            or chunk["source_object_key"] != payload["source_object_key"]
        ):
            raise EvidenceProcessingError("invalid_extraction", "chunk provenance is inconsistent")
        if chunk["untrusted"] is not True or chunk["model_use_allowed"] is not False:
            raise EvidenceProcessingError("invalid_extraction", "chunk trust flags are invalid")


def _column_name(number: int) -> str:
    result = ""
    value = number
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
