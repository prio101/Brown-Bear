"""Agent tool configuration, as reported by a machine (spec 008 §8.2).

One row per *address*, and the address is the feature:

    machine  →  Global | project  →  tool (claude, qwen)  →  path

Four columns rather than a joined path string, so the tree groups on real columns
and so a project literally named ``global`` cannot collide with the global scope.

``content`` holds what was stored, which is not always what was sent: values that
look like credentials are masked before this row is written, and ``redactions``
counts how many spans were. ``sha256`` is the digest of the content **as
received** — change detection has to work on the real bytes even though the real
bytes are deliberately not what was kept.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from brownbear.db import Base


class ConfigContentKind(enum.StrEnum):
    """Why a row may have no content, stated rather than left as a null to read."""

    #: Decoded as UTF-8 and stored (redacted). The normal case.
    text = "text"
    #: Not UTF-8. Address, size and digest recorded; nothing to read.
    binary = "binary"
    #: Over the per-file cap. Recorded rather than truncated — a truncated
    #: configuration file is a configuration that exists nowhere.
    too_large = "too_large"


class ConfigStatus(enum.StrEnum):
    synced = "synced"
    #: Present in an earlier sync of this branch and absent from the latest one,
    #: when that sync asked for reconciliation. The last content is kept: a file
    #: that disappeared from a machine is information, not an absence.
    removed = "removed"


class AgentConfig(Base):
    __tablename__ = "agent_configs"

    #: a_<sha256(machine\0scope\0project\0tool\0path)[:32]> — the Key Based layer's
    #: convention, extended to an address rather than to content.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    machine: Mapped[str] = mapped_column(String(128), nullable=False)
    #: "global" (the machine-wide ~/.claude) or "project" (a checkout's own
    #: directory). A validated String rather than a Postgres enum for one blunt
    #: reason: `global` cannot be a Python enum member name, and working around
    #: that needs `values_callable` — a mapping the test suite cannot exercise,
    #: because every test here fakes the database. Validated in `agents.py`
    #: against SCOPES, which is checked on every write path.
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Normalised with gateway.normalise_project(), so a branch scopes exactly as
    #: exchanges and chunks already do. Empty string — never null — when global, so
    #: the unique constraint below actually constrains.
    project: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    #: Allowlisted in the application rather than in a Postgres type: adding
    #: `codex` should be a one-line change, not an ALTER TYPE in a migration.
    tool: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Relative, POSIX-separated. Never used to build a filesystem path — these
    #: rows live in Postgres — but it is rendered on a page, so it is validated.
    path: Mapped[str] = mapped_column(String(512), nullable=False)

    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_kind: Mapped[ConfigContentKind] = mapped_column(
        Enum(ConfigContentKind, name="agent_content_kind", native_enum=True),
        nullable=False,
        default=ConfigContentKind.text,
    )
    #: How many masked spans the stored text contains — this server's, plus any the
    #: client applied before sending. Counted over what was stored rather than over
    #: this server's own pass: the number's job is to tell a reader how much of the
    #: file they are not seeing, and a server-only count reads as "nothing was
    #: hidden" for a file the client had already masked.
    redactions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[ConfigStatus] = mapped_column(
        Enum(ConfigStatus, name="agent_config_status", native_enum=True),
        nullable=False,
        default=ConfigStatus.synced,
    )
    #: Bumped only when the digest changes, so "revision 4" means four distinct
    #: contents and not four syncs.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Belt and braces beside the derived primary key: if id derivation ever
        # changes or collides, this fails loudly instead of merging two machines'
        # files into one row.
        UniqueConstraint(
            "machine", "scope_kind", "project", "tool", "path", name="uq_agent_configs_address"
        ),
        # The tree and every listing read a branch prefix; nothing queries a path
        # across machines.
        Index("ix_agent_configs_branch", "machine", "scope_kind", "project", "tool"),
        # Staleness: "which machines have stopped reporting" is a range scan.
        Index("ix_agent_configs_synced", "last_synced_at"),
    )


class AgentConfigRevision(Base):
    """One past content of one configuration file (spec 010).

    `agent_configs` holds what a machine has *now*; this holds what it had before.
    That is the difference between a visible copy and a backup, and it is the whole
    reason this table exists — spec 008 shipped without it deliberately, and the
    first question asked of the result was how to get an earlier version back.

    A row is written only when the content actually changes. Re-syncing an
    unchanged directory writes nothing here, so the table grows with edits rather
    than with syncs — which matters when a machine syncs on every session and edits
    its settings twice a year.

    **The content stored here is redacted, exactly as in `agent_configs`.** A
    revision is therefore restorable only when nothing was masked in it, and the
    pull path says so per file rather than handing back a file that looks right and
    does not work.
    """

    __tablename__ = "agent_config_revisions"

    #: r_<sha256(config_id\0revision)[:32]> — the Key Based layer's rule again, so
    #: re-writing the same revision is an upsert rather than a duplicate.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: CASCADE at the database as well as an explicit delete in the service: a
    #: revision whose file is gone is unreachable by every read path here, and
    #: unreachable rows that still consume disk are how a table becomes a mystery.
    config_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_configs.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)

    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_kind: Mapped[ConfigContentKind] = mapped_column(
        Enum(ConfigContentKind, name="agent_content_kind", native_enum=True),
        nullable=False,
        default=ConfigContentKind.text,
    )
    redactions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: When a newer revision superseded this one. Null means it is the current
    #: content — the same fact `agent_configs.revision` carries, kept here too so a
    #: history query needs no join to know where it ends.
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("config_id", "revision", name="uq_agent_config_revisions"),
        # Every read is "this file's history, newest first".
        Index("ix_agent_config_revisions_file", "config_id", "revision"),
    )
