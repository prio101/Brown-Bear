"""Agent configuration revision history (spec 010)

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-19

Spec 008 stored what a machine has now. This stores what it had before, which is
the difference between a visible copy and a backup.

The existing rows are backfilled with one revision each, holding their current
content. Without it, every file synced before this migration would report "no
history" while carrying a revision number above 1 — a table that contradicts the
row pointing at it is worse than an empty one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Created by 0007 and reused here; create_type=False so this migration does not
# try to create it a second time.
CONTENT_KIND = postgresql.ENUM(
    "text", "binary", "too_large", name="agent_content_kind", create_type=False
)


def upgrade() -> None:
    op.create_table(
        "agent_config_revisions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("config_id", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_kind", CONTENT_KIND, nullable=False, server_default="text"),
        sa.Column("redactions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["config_id"], ["agent_configs.id"], ondelete="CASCADE",
            name="fk_agent_config_revisions_file",
        ),
        sa.UniqueConstraint("config_id", "revision", name="uq_agent_config_revisions"),
    )
    op.create_index(
        "ix_agent_config_revisions_file", "agent_config_revisions", ["config_id", "revision"]
    )

    # Backfill: one revision per existing file, holding what it holds today. Done in
    # Python rather than SQL because deriving the id needs sha256, and getting that
    # in a portable statement means either the pgcrypto extension — a strange
    # dependency to add for one INSERT — or a dialect-specific branch.
    _backfill()


def _backfill() -> None:
    import hashlib

    bind = op.get_bind()
    existing = {
        row[0]
        for row in bind.execute(sa.text("SELECT config_id FROM agent_config_revisions")).fetchall()
    }
    rows = bind.execute(
        sa.text(
            "SELECT id, revision, sha256, size_bytes, content, content_kind, redactions, "
            "changed_at FROM agent_configs"
        )
    ).fetchall()
    for row in rows:
        if row[0] in existing:
            continue
        key = f"{row[0]}\0{row[1]}".encode()
        bind.execute(
            sa.text(
                "INSERT INTO agent_config_revisions "
                "(id, config_id, revision, sha256, size_bytes, content, content_kind, "
                " redactions, created_at, replaced_at) "
                "VALUES (:id, :config_id, :revision, :sha256, :size_bytes, :content, "
                " :content_kind, :redactions, :created_at, NULL)"
            ),
            {
                "id": "r_" + hashlib.sha256(key).hexdigest()[:32],
                "config_id": row[0],
                "revision": row[1],
                "sha256": row[2],
                "size_bytes": row[3],
                "content": row[4],
                "content_kind": row[5],
                "redactions": row[6],
                "created_at": row[7],
            },
        )


def downgrade() -> None:
    op.drop_index("ix_agent_config_revisions_file", table_name="agent_config_revisions")
    op.drop_table("agent_config_revisions")
