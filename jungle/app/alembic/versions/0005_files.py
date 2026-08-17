"""Ingested files (spec 007)

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False is load-bearing: `op.create_table` would otherwise emit its own
# CREATE TYPE for this column, colliding with the explicit, idempotent creation
# below. Creating it explicitly is what lets `downgrade` drop it again.
FILE_STATUS = postgresql.ENUM(
    "indexed", "stored", "failed", "missing", name="file_status", create_type=False
)


def upgrade() -> None:
    # checkfirst so a re-run after a partial failure is safe.
    FILE_STATUS.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "files",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("project", sa.String(length=128), nullable=False, server_default="default"),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extractor", sa.String(length=128), nullable=True),
        sa.Column("extracted_by", sa.String(length=128), nullable=True),
        sa.Column("has_preview", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("preview_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", FILE_STATUS, nullable=False, server_default="stored"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tags", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        # One row per distinct content: the same file from three machines dedupes
        # here as well as in the blob store.
        sa.UniqueConstraint("sha256", name="uq_files_sha256"),
    )
    op.create_index("ix_files_project_created", "files", ["project", "created_at"])
    op.create_index("ix_files_status", "files", ["status"])


def downgrade() -> None:
    op.drop_index("ix_files_status", table_name="files")
    op.drop_index("ix_files_project_created", table_name="files")
    op.drop_table("files")
    FILE_STATUS.drop(op.get_bind(), checkfirst=True)
