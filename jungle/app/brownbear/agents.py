"""Agent tool configuration sync (spec 008 §8.1, §8.3).

A machine sends the contents of its `.claude/` or `.qwen/` directory; this module
addresses it, strips what looks like a credential, and stores it.

Three things it is careful about, in order of how badly they would go wrong:

**Secrets are masked here, not on the client.** A `.claude` directory routinely
contains an API key — an `env` block in `settings.local.json`, a server definition
in `.mcp.json`. This endpoint is reachable from the internet behind one shared
secret and its contents are rendered on a dashboard page, so the redaction that
matters is the one that runs before the row is written. The client redacts too;
that is a courtesy, and an old client, a hand-rolled `curl` or an untouched script
all bypass it.

**Paths arrive from a client and are never trusted.** Nothing here writes to a
filesystem, so traversal cannot escape anything — but a path is an identity and a
rendered string, so it is validated rather than sanitised, and a zip entry name
gets exactly the same treatment as a JSON path.

**This is not the memory.** Nothing in this module embeds, chunks or touches
Chroma. Configuration is not material anyone asked a question about, and a
`settings.json` scoring 0.7 against a coding prompt would be noise *inside*
`knowledge`, where the two-collection split cannot filter it.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import anyio.to_thread
from sqlalchemy import Integer, case, func, select

from brownbear import gateway
from brownbear.config import get_settings
from brownbear.db import session_scope
from brownbear.models.agents import AgentConfig, ConfigContentKind, ConfigStatus

logger = logging.getLogger(__name__)

SCOPE_GLOBAL = "global"
SCOPE_PROJECT = "project"
SCOPES = frozenset({SCOPE_GLOBAL, SCOPE_PROJECT})

#: The tools whose configuration this understands. An allowlist in code rather
#: than a Postgres enum, so adding `codex` is a one-line change instead of an
#: ALTER TYPE in a migration. A typo must never quietly create a third branch.
TOOLS: tuple[str, ...] = ("claude", "qwen")

#: What a machine calls itself. Dots and dashes survive on purpose: collapsing
#: `mahabubs-mbp.local` the way project names are collapsed would leave the tree
#: unreadable, and a hostname is a label here rather than a matching key.
_MACHINE_NOISE = re.compile(r"[^a-z0-9._-]+")

MAX_PATH_CHARS = 512
MAX_MACHINE_CHARS = 128


class ConfigRejected(Exception):
    """One file is unusable. Never fails the sync it arrived in.

    A single bad path in a forty-file directory walk must not cost the other
    thirty-nine — the reason is reported per path and the rest are stored.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --- address ----------------------------------------------------------------


def normalise_machine(value: str) -> str:
    slug = _MACHINE_NOISE.sub("-", (value or "").strip().lower()).strip("-.")
    return slug[:MAX_MACHINE_CHARS] or "unknown"


def normalise_tool(value: str) -> str:
    tool = (value or "").strip().lower()
    if tool not in TOOLS:
        raise ConfigRejected(f"unknown tool {tool!r}; expected one of {', '.join(TOOLS)}")
    return tool


def normalise_scope(scope: str, project: str) -> tuple[str, str]:
    """Return (scope_kind, project) for a request's scope.

    `project` is normalised with the gateway's rule, unchanged, so a branch scopes
    exactly as exchanges, chunks and files already do — and collapses the same way:
    `Brown-Bear`, `brownbear` and `brown_bear` are one branch.
    """
    kind = (scope or SCOPE_PROJECT).strip().lower()
    if kind not in SCOPES:
        raise ConfigRejected(f"unknown scope {kind!r}; expected one of {', '.join(sorted(SCOPES))}")
    if kind == SCOPE_GLOBAL:
        # Empty string, never null: the unique constraint on the address has to
        # actually constrain, and Postgres treats nulls as distinct.
        return SCOPE_GLOBAL, ""
    raw = (project or "").strip()
    if not raw:
        raise ConfigRejected("a project-scoped sync needs a project name")
    return SCOPE_PROJECT, gateway.normalise_project(raw)


def normalise_path(value: str) -> str:
    """A relative, POSIX-separated path inside the tool directory.

    Rejected rather than repaired. A path that has to be rewritten to be safe is a
    path whose meaning is already unclear, and silently storing `etc/passwd` for a
    client that sent `../../etc/passwd` invents a file nobody has.
    """
    raw = (value or "").strip()
    if not raw:
        raise ConfigRejected("empty path")
    if "\x00" in raw:
        raise ConfigRejected("path contains a NUL byte")
    if "\\" in raw:
        raise ConfigRejected("path contains a backslash; send POSIX separators")
    if raw.startswith("/") or re.match(r"^[a-zA-Z]:", raw):
        raise ConfigRejected("path must be relative to the tool directory")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ConfigRejected("path escapes the tool directory")
    cleaned = "/".join(parts)
    if not cleaned:
        raise ConfigRejected("empty path")
    if len(cleaned) > MAX_PATH_CHARS:
        raise ConfigRejected(f"path exceeds {MAX_PATH_CHARS} characters")
    return cleaned


def config_id(machine: str, scope_kind: str, project: str, tool: str, path: str) -> str:
    """Identity of an address, not of content.

    NUL-joined so `a/b` + `c` cannot hash the same as `a` + `b/c`; the separator
    cannot occur in any component because `normalise_path` rejects it.
    """
    key = "\0".join((machine, scope_kind, project, tool, path)).encode()
    return f"a_{hashlib.sha256(key).hexdigest()[:32]}"


def branch_label(machine: str, scope_kind: str, project: str, tool: str) -> str:
    """Human-readable address, for a response and for a log line."""
    scope = "global" if scope_kind == SCOPE_GLOBAL else project
    return f"{machine}/{scope}/{tool}"


# --- what is never stored ---------------------------------------------------

#: Files whose entire purpose is to hold a credential. Masking one leaves nothing
#: to read, so they are refused instead — with the reason, because a silent skip
#: reads as "synced" to whoever is looking at the tree.
DENIED_BASENAMES = frozenset(
    {".credentials.json", "credentials.json", ".netrc", "id_rsa", "id_ed25519"}
)
DENIED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore")


def denial_reason(path: str) -> str | None:
    base = path.rsplit("/", 1)[-1].lower()
    if base in DENIED_BASENAMES:
        return f"{base} exists to hold a credential; it is never stored here"
    if base == ".env" or base.startswith(".env."):
        return "an .env file exists to hold credentials; it is never stored here"
    if base.endswith(DENIED_SUFFIXES):
        return "key material is never stored here"
    return None


# --- redaction --------------------------------------------------------------

MASK = "«redacted»"

#: Run over the *text*, deliberately, not over parsed JSON. A `settings.json` with
#: a trailing comma still has to be masked, and `json.loads` would refuse it and
#: leave the file stored verbatim — and a hand-edited, slightly broken settings
#: file is exactly where a key is most likely to be sitting.
#:
#: Every pattern names its surviving context `pre`, and `post` where the match has
#: a closing fence. Positional groups were a trap here: a two-group pattern reads
#: identically whether the second group is a closing quote to keep or the secret
#: itself, and getting it backwards puts the key straight back into the text.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "anything_key": "value" — the JSON shape almost every tool uses.
    re.compile(
        r'(?P<pre>"[A-Za-z0-9_.\-]*'
        r"(?:token|api[_-]?key|secret|password|passwd|authorization|credential)"
        # `[^"\\\s]` and not `[^"\\]`: the value has to be one unbroken token.
        # Without that this masked `"Authorization": "Bearer "` in a hook script —
        # eager enough to garble source code while protecting nothing. A real
        # credential never contains a space; a passphrase that does is missed, and
        # that is the accepted cost of the trade.
        r'[A-Za-z0-9_.\-]*"\s*:\s*")[^"\\\s]{4,}(?P<post>")',
        re.IGNORECASE,
    ),
    # KEY=value in a shell or ini fragment.
    re.compile(
        r"(?P<pre>^[A-Za-z0-9_.\-]*"
        r"(?:TOKEN|API[_-]?KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL)"
        r"[A-Za-z0-9_.\-]*\s*=\s*)\S{4,}$",
        re.IGNORECASE | re.MULTILINE,
    ),
    # Provider-shaped literals, wherever they appear — including in a comment, a
    # README or a shell snippet, where no key name precedes them.
    re.compile(r"(?P<pre>sk-ant-)[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?P<pre>sk-)(?!ant-)[A-Za-z0-9]{20,}"),
    re.compile(r"(?P<pre>gh[pousr]_)[A-Za-z0-9]{20,}"),
    re.compile(r"(?P<pre>AKIA)[0-9A-Z]{12,}"),
    re.compile(r"(?P<pre>xox[baprs]-)[A-Za-z0-9-]{10,}"),
    re.compile(r"(?P<pre>Bearer\s+)[A-Za-z0-9._\-]{20,}"),
    re.compile(
        r"(?P<pre>-----BEGIN [A-Z ]*PRIVATE KEY-----)[\s\S]+?"
        r"(?P<post>-----END [A-Z ]*PRIVATE KEY-----)"
    ),
)

#: Every value inside an `env` object, whatever it is called. Claude Code's
#: settings put environment variables there, and an environment variable is a
#: credential often enough that name-matching each one is the wrong bet.
#:
#: `[^{}]*` keeps this to a flat object — which is what `env` is. A nested object
#: inside `env` would end the match early; its values then fall to the patterns
#: above rather than escaping redaction entirely.
_ENV_BLOCK = re.compile(r'("env"\s*:\s*\{)([^{}]*)(\})', re.IGNORECASE)
_ENV_VALUE = re.compile(r'(:\s*")([^"\\]{1,})(")')


def _mask_match(match: re.Match[str]) -> str:
    pre = match.group("pre")
    post = match.groupdict().get("post") or ""
    return f"{pre}{MASK}{post}"


def redact(text: str) -> tuple[str, int]:
    """Mask credential-shaped values. Returns the text and how many were masked.

    Masking rather than refusing: a `settings.json` with one `env` block is the
    common case, and refusing the whole file loses the forty lines that were the
    point. The count is stored and shown, so a reader knows how much of the file
    they are not seeing.
    """
    masked = 0

    def _env(match: re.Match[str]) -> str:
        def _value(inner: re.Match[str]) -> str:
            nonlocal masked
            if inner.group(2) == MASK:
                return inner.group(0)
            masked += 1
            return f"{inner.group(1)}{MASK}{inner.group(3)}"

        return f"{match.group(1)}{_ENV_VALUE.sub(_value, match.group(2))}{match.group(3)}"

    result = _ENV_BLOCK.sub(_env, text)

    def _one(match: re.Match[str]) -> str:
        nonlocal masked
        # Already masked, by the env pass or by an earlier pattern. Counting it
        # twice would overstate how much of the file is hidden.
        if MASK in match.group(0):
            return match.group(0)
        masked += 1
        return _mask_match(match)

    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(_one, result)

    return result, masked


# --- decoding ---------------------------------------------------------------


def decode(data: bytes, *, max_bytes: int) -> tuple[str | None, ConfigContentKind]:
    """Text, or a stated reason there is none.

    Never truncates. A configuration file cut off at 256 KB is a configuration
    that exists on no machine, and storing one would be worse than storing the
    fact that the file is large.
    """
    if len(data) > max_bytes:
        return None, ConfigContentKind.too_large
    try:
        return data.decode("utf-8"), ConfigContentKind.text
    except UnicodeDecodeError:
        return None, ConfigContentKind.binary


# --- zip --------------------------------------------------------------------


@dataclass(frozen=True)
class ZipLimits:
    max_entries: int
    #: Total uncompressed bytes across the archive.
    max_total_bytes: int
    max_entry_bytes: int
    #: Refuse an archive whose declared expansion is this many times its own size.
    #: A 2 MB zip that claims to expand to 4 GB is a bomb, and the claim is enough
    #: to refuse it — no expansion required.
    max_ratio: int = 200


class ZipRejected(Exception):
    """The whole archive is unusable. Unlike ConfigRejected, this fails the sync."""


def unpack_zip(payload: bytes, limits: ZipLimits) -> list[tuple[str, bytes]]:
    """Read an archive into (path, bytes) pairs, refusing the dangerous shapes.

    `zipfile.extractall` is not used and could not be: it writes wherever an entry
    name points. Nothing here touches a filesystem — but an entry name still
    becomes a stored path, so it goes through `normalise_path` like anything else.

    `file_size` from the header is a *claim*. It is read to refuse an obvious bomb
    before expanding anything, and the real cap is then enforced against what
    actually comes out.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ZipRejected(f"not a readable zip archive: {exc}") from exc

    entries = [info for info in archive.infolist() if not info.is_dir()]
    if len(entries) > limits.max_entries:
        raise ZipRejected(f"archive holds {len(entries)} files; the limit is {limits.max_entries}")

    declared = sum(info.file_size for info in entries)
    if declared > limits.max_total_bytes:
        raise ZipRejected(
            f"archive expands to {declared} bytes; the limit is {limits.max_total_bytes}"
        )
    if payload and declared / max(len(payload), 1) > limits.max_ratio:
        raise ZipRejected("archive's declared expansion ratio is implausible; refused unexpanded")

    files: list[tuple[str, bytes]] = []
    total = 0
    for info in entries:
        # Symlinks and devices carry their target as the entry body; storing one
        # would record a path as though it were a configuration file.
        if (info.external_attr >> 16) & 0o170000 not in (0, 0o100000):
            continue
        with archive.open(info) as handle:
            data = handle.read(limits.max_entry_bytes + 1)
        total += len(data)
        if total > limits.max_total_bytes:
            raise ZipRejected(
                f"archive expanded past {limits.max_total_bytes} bytes; refused mid-read"
            )
        files.append((info.filename, data))
    return files


# --- persistence ------------------------------------------------------------
# Sync SQLAlchemy, run off the event loop by the router, matching the rest of the
# app (see db.py).


@dataclass(frozen=True)
class Branch:
    machine: str
    scope_kind: str
    project: str
    tool: str

    @property
    def label(self) -> str:
        return branch_label(self.machine, self.scope_kind, self.project, self.tool)


def _branch_filter(query, branch: Branch):
    return query.where(
        AgentConfig.machine == branch.machine,
        AgentConfig.scope_kind == branch.scope_kind,
        AgentConfig.project == branch.project,
        AgentConfig.tool == branch.tool,
    )


def _apply(record: AgentConfig, incoming: dict[str, Any], now: datetime) -> str:
    """Update a row in place and say what happened to it.

    Change is judged on the digest of the content *as received*, never on the
    stored text: the stored text is redacted, so two files differing only in their
    secret would otherwise look identical and the newer one would never land.
    """
    changed = record.sha256 != incoming["sha256"]
    record.last_synced_at = now
    was_removed = record.status == ConfigStatus.removed
    record.status = ConfigStatus.synced
    record.removed_at = None

    if not changed and not was_removed:
        return "unchanged"

    record.sha256 = incoming["sha256"]
    record.size_bytes = incoming["size_bytes"]
    record.content = incoming["content"]
    record.content_kind = incoming["content_kind"]
    record.redactions = incoming["redactions"]
    if changed:
        record.revision += 1
        record.changed_at = now
    return "updated"


def _sync_sync(
    branch: Branch, incoming: list[dict[str, Any]], *, prune: bool, now: datetime
) -> tuple[list[dict[str, Any]], int]:
    """Upsert a branch's files, and optionally reconcile what is missing.

    One transaction for the whole branch: a sync that half-landed would leave a
    tree that agrees with no machine, and reconciliation in particular has to see
    the same set of rows it just wrote.
    """
    outcomes: list[dict[str, Any]] = []
    with session_scope() as session:
        seen: set[str] = set()
        for values in incoming:
            identifier = values["id"]
            seen.add(identifier)
            record = session.get(AgentConfig, identifier)
            if record is None:
                record = AgentConfig(
                    id=identifier,
                    machine=branch.machine,
                    scope_kind=branch.scope_kind,
                    project=branch.project,
                    tool=branch.tool,
                    path=values["path"],
                    sha256=values["sha256"],
                    size_bytes=values["size_bytes"],
                    content=values["content"],
                    content_kind=values["content_kind"],
                    redactions=values["redactions"],
                    status=ConfigStatus.synced,
                    revision=1,
                    first_seen_at=now,
                    last_synced_at=now,
                    changed_at=now,
                )
                session.add(record)
                outcome = "stored"
            else:
                outcome = _apply(record, values, now)
            outcomes.append(
                {
                    "path": values["path"],
                    "config_id": identifier,
                    "outcome": outcome,
                    "revision": record.revision,
                    "redactions": values["redactions"],
                    "content_kind": str(values["content_kind"]),
                }
            )

        removed = 0
        if prune:
            # Scoped to the branch being synced, never wider: a machine syncing its
            # `claude` project config must not touch its own global config, let
            # alone another machine's.
            rows = session.scalars(_branch_filter(select(AgentConfig), branch)).all()
            for row in rows:
                if row.id in seen or row.status == ConfigStatus.removed:
                    continue
                row.status = ConfigStatus.removed
                row.removed_at = now
                removed += 1
                outcomes.append(
                    {
                        "path": row.path,
                        "config_id": row.id,
                        "outcome": "removed",
                        "revision": row.revision,
                        "redactions": row.redactions,
                        "content_kind": str(row.content_kind),
                    }
                )
        session.flush()
    return outcomes, removed


def _list_sync(
    *,
    machine: str | None,
    scope_kind: str | None,
    project: str | None,
    tool: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[AgentConfig], int]:
    with session_scope() as session:
        query = select(AgentConfig)
        counter = select(func.count()).select_from(AgentConfig)
        for column, value in (
            (AgentConfig.machine, machine),
            (AgentConfig.scope_kind, scope_kind),
            (AgentConfig.project, project),
            (AgentConfig.tool, tool),
            (AgentConfig.status, status),
        ):
            if value:
                query = query.where(column == value)
                counter = counter.where(column == value)

        total = session.scalar(counter) or 0
        rows = list(
            session.scalars(
                query.order_by(AgentConfig.machine, AgentConfig.tool, AgentConfig.path)
                .limit(limit)
                .offset(offset)
            )
        )
        for row in rows:
            session.expunge(row)
        return rows, total


def _get_sync(identifier: str) -> AgentConfig | None:
    with session_scope() as session:
        record = session.get(AgentConfig, identifier)
        if record is not None:
            session.expunge(record)
        return record


def _delete_sync(identifier: str) -> AgentConfig | None:
    with session_scope() as session:
        record = session.get(AgentConfig, identifier)
        if record is None:
            return None
        session.delete(record)
        # Flush BEFORE expunging, and the order is load-bearing: `expunge` evicts
        # the instance from the session, which discards the pending delete along
        # with it. Expunging first leaves a route that reports `deleted: true`
        # while the row is still there. Flushing emits the DELETE, so the later
        # expunge only detaches an object whose deletion has already been sent.
        session.flush()
        session.expunge(record)
        return record


def _inventory_sync() -> list[dict[str, Any]]:
    """One row per (machine, scope, project, tool), aggregated in the database.

    Grouped in SQL rather than by reading every row: the page needs counts and
    ages, and a corpus of configuration text is the one thing it must not load to
    produce them.
    """
    with session_scope() as session:
        rows = session.execute(
            select(
                AgentConfig.machine,
                AgentConfig.scope_kind,
                AgentConfig.project,
                AgentConfig.tool,
                func.count().label("files"),
                func.coalesce(func.sum(AgentConfig.size_bytes), 0).label("bytes"),
                func.coalesce(func.sum(AgentConfig.redactions), 0).label("redactions"),
                func.max(AgentConfig.last_synced_at).label("last_synced_at"),
                func.max(AgentConfig.changed_at).label("changed_at"),
                # CASE rather than a cast of the boolean: `sum(bool)` is a type
                # error on Postgres, and the cast form differs per dialect.
                func.sum(
                    case((AgentConfig.status == ConfigStatus.removed, 1), else_=0).cast(Integer)
                ).label("removed"),
            )
            .group_by(
                AgentConfig.machine,
                AgentConfig.scope_kind,
                AgentConfig.project,
                AgentConfig.tool,
            )
            .order_by(
                AgentConfig.machine,
                AgentConfig.scope_kind,
                AgentConfig.project,
                AgentConfig.tool,
            )
        ).all()

    return [
        {
            "machine": row.machine,
            "scope_kind": row.scope_kind,
            "project": row.project,
            "tool": row.tool,
            "files": int(row.files or 0),
            "bytes": int(row.bytes or 0),
            "redactions": int(row.redactions or 0),
            "removed": int(row.removed or 0),
            "last_synced_at": row.last_synced_at,
            "changed_at": row.changed_at,
        }
        for row in rows
    ]


# --- async wrappers ---------------------------------------------------------


async def listing(
    *,
    machine: str | None = None,
    scope_kind: str | None = None,
    project: str | None = None,
    tool: str | None = None,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[AgentConfig], int]:
    return await anyio.to_thread.run_sync(
        lambda: _list_sync(
            machine=machine,
            scope_kind=scope_kind,
            project=project,
            tool=tool,
            status=status,
            limit=limit,
            offset=offset,
        )
    )


async def get(identifier: str) -> AgentConfig | None:
    return await anyio.to_thread.run_sync(_get_sync, identifier)


async def remove(identifier: str) -> dict[str, Any] | None:
    record = await anyio.to_thread.run_sync(_delete_sync, identifier)
    if record is None:
        return None
    return {"config_id": record.id, "path": record.path, "branch": branch_label(
        record.machine, record.scope_kind, record.project, record.tool
    )}


# --- the sync itself --------------------------------------------------------


def prepare(branch: Branch, path: str, data: bytes) -> dict[str, Any]:
    """Turn one incoming file into the row that will be written.

    The digest is taken over the bytes as received — before redaction — so change
    detection sees the machine's real content. The redacted text is what is kept.
    """
    settings = get_settings()
    cleaned = normalise_path(path)
    if (reason := denial_reason(cleaned)) is not None:
        raise ConfigRejected(reason)

    text, kind = decode(data, max_bytes=settings.max_config_file_bytes)
    redactions = 0
    if text is not None:
        text, _ = redact(text)
        # Counted over the STORED text rather than taken from this pass, so it
        # includes masks the client applied before sending. The number's job is to
        # tell a reader how much of the file they are not seeing; a server-only
        # count reported 0 for a file already full of masks, which read as "nothing
        # was hidden here" about exactly the files where something was.
        redactions = text.count(MASK)

    return {
        "id": config_id(branch.machine, branch.scope_kind, branch.project, branch.tool, cleaned),
        "path": cleaned,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "content": text,
        "content_kind": kind,
        "redactions": redactions,
    }


async def sync(
    branch: Branch, files: Iterable[tuple[str, bytes]], *, prune: bool
) -> dict[str, Any]:
    """Store a branch's files and report what happened to each one.

    A rejected file is reported, not raised: one unusable path in a forty-file
    directory walk must not cost the other thirty-nine.
    """
    settings = get_settings()
    prepared: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for path, data in files:
        if len(prepared) >= settings.max_sync_files:
            skipped.append(
                {
                    "path": path,
                    "reason": f"more than {settings.max_sync_files} files in one sync",
                    "outcome": "skipped",
                }
            )
            continue
        try:
            values = prepare(branch, path, data)
        except ConfigRejected as exc:
            skipped.append({"path": path, "reason": exc.reason, "outcome": "skipped"})
            continue
        if values["id"] in seen_ids:
            # Two entries normalising to one path — `./a` and `a` from a zip, say.
            # Last would win silently; saying so is cheap.
            skipped.append(
                {"path": path, "reason": "duplicate path in this sync", "outcome": "skipped"}
            )
            continue
        seen_ids.add(values["id"])
        prepared.append(values)

    now = datetime.now(UTC)
    outcomes, removed = await anyio.to_thread.run_sync(
        lambda: _sync_sync(branch, prepared, prune=prune, now=now)
    )

    tally = {"stored": 0, "updated": 0, "unchanged": 0, "removed": 0}
    for outcome in outcomes:
        tally[outcome["outcome"]] = tally.get(outcome["outcome"], 0) + 1

    # One line per sync, in the app log: a configuration store nobody can see the
    # writes to is a configuration store nobody trusts.
    logger.info(
        "agent config sync %s: %d new, %d changed, %d unchanged, %d removed, %d skipped",
        branch.label,
        tally["stored"],
        tally["updated"],
        tally["unchanged"],
        removed,
        len(skipped),
    )

    return {
        "branch": branch.label,
        "machine": branch.machine,
        "scope": branch.scope_kind,
        "project": branch.project,
        "tool": branch.tool,
        "received": len(prepared) + len(skipped),
        "stored": tally["stored"],
        "updated": tally["updated"],
        "unchanged": tally["unchanged"],
        "removed": removed,
        "skipped": len(skipped),
        "redactions": sum(int(v["redactions"]) for v in prepared),
        "pruned": prune,
        "files": outcomes + skipped,
    }


async def inventory() -> dict[str, Any]:
    """The tree the dashboard navigates: machine → scope → tool.

    Assembled from the grouped query rather than from rows, so the response stays
    the same size whether a machine has ten files or a thousand.
    """
    settings = get_settings()
    groups = await anyio.to_thread.run_sync(_inventory_sync)

    machines: dict[str, dict[str, Any]] = {}
    for group in groups:
        machine = machines.setdefault(
            group["machine"],
            {"machine": group["machine"], "scopes": [], "files": 0, "bytes": 0,
             "removed": 0, "redactions": 0, "last_synced_at": None},
        )
        scope_key = (group["scope_kind"], group["project"])
        scope = next(
            (s for s in machine["scopes"]
             if (s["scope"], s["project"]) == scope_key),
            None,
        )
        if scope is None:
            scope = {
                "scope": group["scope_kind"],
                "project": group["project"],
                # "Global" is the label the requirement names; a project scope is
                # labelled by its own normalised name.
                "label": "Global" if group["scope_kind"] == SCOPE_GLOBAL else group["project"],
                "tools": [],
                "files": 0,
                "bytes": 0,
            }
            machine["scopes"].append(scope)

        last = group["last_synced_at"]
        scope["tools"].append(
            {
                "tool": group["tool"],
                "files": group["files"],
                "bytes": group["bytes"],
                "removed": group["removed"],
                "redactions": group["redactions"],
                "last_synced_at": last.isoformat() if last else None,
                "changed_at": group["changed_at"].isoformat() if group["changed_at"] else None,
            }
        )
        scope["files"] += group["files"]
        scope["bytes"] += group["bytes"]
        machine["files"] += group["files"]
        machine["bytes"] += group["bytes"]
        machine["removed"] += group["removed"]
        machine["redactions"] += group["redactions"]
        if last is not None:
            current = machine["last_synced_at"]
            iso = last.isoformat()
            machine["last_synced_at"] = iso if current is None or iso > current else current

    ordered = sorted(machines.values(), key=lambda m: m["machine"])
    return {
        "machines": ordered,
        "totals": {
            "machines": len(ordered),
            "files": sum(m["files"] for m in ordered),
            "bytes": sum(m["bytes"] for m in ordered),
            "removed": sum(m["removed"] for m in ordered),
            "redactions": sum(m["redactions"] for m in ordered),
        },
        "tools": list(TOOLS),
        # The page decides staleness rather than the row: "when did this machine
        # last report" is the question, and it needs the threshold to answer it.
        "stale_after_hours": settings.config_stale_hours,
    }


def to_dict(record: AgentConfig, *, include_content: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "config_id": record.id,
        "machine": record.machine,
        "scope": record.scope_kind,
        "project": record.project,
        "label": "Global" if record.scope_kind == SCOPE_GLOBAL else record.project,
        "tool": record.tool,
        "path": record.path,
        "sha256": record.sha256,
        "size_bytes": record.size_bytes,
        "content_kind": str(record.content_kind),
        "redactions": record.redactions,
        "status": str(record.status),
        "revision": record.revision,
        "first_seen_at": record.first_seen_at.isoformat() if record.first_seen_at else None,
        "last_synced_at": record.last_synced_at.isoformat() if record.last_synced_at else None,
        "changed_at": record.changed_at.isoformat() if record.changed_at else None,
        "removed_at": record.removed_at.isoformat() if record.removed_at else None,
    }
    if include_content:
        payload["content"] = record.content
    return payload
