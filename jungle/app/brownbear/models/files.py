"""Ingested files (spec 007 §7.2).

One row per distinct *content*, not per upload: the primary key is derived from the
SHA-256 of the bytes, so the same PDF arriving from three machines is one row. What
varies per upload — which machine sent it, what extracted it — is recorded on that
single row rather than duplicated into three.

`extracted_text` holds the whole extraction, not just what was chunked. Keeping
only chunks makes a bad extraction invisible: you would see poor retrieval with no
way to tell whether the scan was unreadable or the embedding was at fault.
"""

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from brownbear.db import Base


class FileStatus(enum.StrEnum):
    """Why a file may not be retrievable, stated rather than inferred."""

    #: Extracted text was chunked and embedded. The normal case.
    indexed = "indexed"
    #: Bytes are held but nothing was indexed — no extraction was supplied, or it
    #: was empty. Downloadable and visible; simply not searchable.
    stored = "stored"
    #: Extraction arrived but embedding failed. Retryable without re-uploading.
    failed = "failed"
    #: The row is here and the blob is not. Volumes get pruned.
    missing = "missing"


class FileRecord(Base):
    __tablename__ = "files"

    #: f_<sha256[:32]> — the Key Based layer's convention, extended to bytes.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    #: Display only. Never used to build a path — a filename is attacker-controlled.
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    #: Sniffed from the bytes, not taken from the client's Content-Type header.
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    #: Normalised scope, identical in form to the one exchanges and chunks use.
    project: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    #: Retrieval label; joins this row to the `source` node the graph already draws.
    source: Mapped[str] = mapped_column(String(512), nullable=False)

    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What produced the text — "pdftotext 24.02", "tesseract 5.3". Recorded because
    #: it cannot be verified here, and a reader comparing a bad retrieval against
    #: its source needs to know what read it.
    extractor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Which machine reported it. Same trust posture as token reporting.
    extracted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    has_preview: Mapped[bool] = mapped_column(default=False, nullable=False)
    preview_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[FileStatus] = mapped_column(
        Enum(FileStatus, name="file_status", native_enum=True),
        nullable=False,
        default=FileStatus.stored,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Free-form, comma-separated. A join table for labels nobody has asked to query
    #: relationally yet would be structure ahead of need.
    tags: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # The list view filters by project and orders by recency; the graph looks
        # files up by project alone.
        Index("ix_files_project_created", "project", "created_at"),
        Index("ix_files_status", "status"),
    )
