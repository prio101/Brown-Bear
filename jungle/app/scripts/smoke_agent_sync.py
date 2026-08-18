#!/usr/bin/env python3
"""End-to-end exercise of the agent configuration endpoints (spec 008).

    python3 scripts/smoke_agent_sync.py

The unit suite fakes the database — deliberately, so it runs anywhere — which
leaves the SQL itself uncovered: the branch transaction, the prune reconciliation
and the grouped inventory rollup are the three pieces most likely to be wrong and
least likely to be caught. This drives all of them through the real routes against
a throwaway SQLite file.

**SQLite is not what production runs.** This is a smoke test, not a guarantee: the
native enum types and the `uq_agent_configs_address` constraint behave differently
there, and the migration itself is PostgreSQL-only. What it does prove is that the
queries compile, the transaction boundaries hold, and the sequence a client
actually performs produces the numbers the API claims.

Exits non-zero on the first disagreement, naming what it expected.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    if actual == expected:
        print(f"  ok    {label}: {actual!r}")
    else:
        failures.append(f"{label}: expected {expected!r}, got {actual!r}")
        print(f"  FAIL  {label}: expected {expected!r}, got {actual!r}")


def main() -> int:
    import os

    # A database already named in the environment is used as-is and assumed
    # migrated — that is how this gets pointed at a real PostgreSQL, where the
    # enums, the unique constraint and the timestamptz defaults actually exist:
    #
    #   BB_DATABASE_URL=postgresql+psycopg://... python3 scripts/smoke_agent_sync.py
    #
    # Otherwise it makes its own throwaway SQLite file, so the script runs anywhere.
    supplied = os.environ.get("BB_DATABASE_URL")
    if not supplied:
        workdir = Path(tempfile.mkdtemp(prefix="bb-smoke-"))
        os.environ["BB_DATABASE_URL"] = f"sqlite+pysqlite:///{workdir / 'smoke.sqlite'}"
    os.environ["BB_SCHEDULER_ENABLED"] = "false"

    from fastapi.testclient import TestClient

    from brownbear import models  # noqa: F401  — registers every table
    from brownbear.config import get_settings
    from brownbear.db import Base, get_engine, reset_engine
    from brownbear.main import create_app

    get_settings.cache_clear()
    reset_engine()
    if not supplied:
        Base.metadata.create_all(get_engine())

    client = TestClient(create_app())

    print(f"database: {os.environ['BB_DATABASE_URL'].split('@')[-1]}")

    # Rows from an earlier run would make every count wrong, and a smoke test that
    # reports the wrong number is worse than none.
    from sqlalchemy import delete

    from brownbear.db import session_scope
    from brownbear.models.agents import AgentConfig

    with session_scope() as session:
        session.execute(
            delete(AgentConfig).where(AgentConfig.machine.in_(("smoke-box.local", "ci-runner-01")))
        )

    print("\n1. first sync of a project branch")
    body = client.post(
        "/ext/agents/sync",
        json={
            "machine": "Smoke-Box.local",
            "scope": "project",
            "project": "Brown-Bear",
            "tool": "claude",
            "prune": True,
            "files": [
                {"path": "settings.json", "content": json.dumps({"model": "claude-opus-5"})},
                {"path": "CLAUDE.md", "content": "# rules\nbe brief\n"},
                {
                    "path": "settings.local.json",
                    "content": json.dumps({"env": {"ANTHROPIC_API_KEY": "sk-ant-abcdefghijklmno"}}),
                },
                # Refused outright rather than masked: nothing is left to read.
                {"path": ".credentials.json", "content": '{"token": "xyzzyxyzzyxyzzy"}'},
                # Rejected without costing the rest of the sync.
                {"path": "../../etc/passwd", "content": "root:x"},
            ],
        },
    ).json()
    check("branch", body["branch"], "smoke-box.local/brownbear/claude")
    check("stored", body["stored"], 3)
    check("skipped", body["skipped"], 2)
    check("masked server-side", body["redactions"], 1)
    check("the key is absent from the response", "sk-ant" in json.dumps(body), False)

    print("\n2. the same sync again — everything unchanged, no revision bumped")
    again = client.post(
        "/ext/agents/sync",
        json={
            "machine": "Smoke-Box.local",
            "project": "Brown-Bear",
            "tool": "claude",
            "prune": True,
            "files": [
                {"path": "settings.json", "content": json.dumps({"model": "claude-opus-5"})},
                {"path": "CLAUDE.md", "content": "# rules\nbe brief\n"},
                {
                    "path": "settings.local.json",
                    "content": json.dumps({"env": {"ANTHROPIC_API_KEY": "sk-ant-abcdefghijklmno"}}),
                },
            ],
        },
    ).json()
    check("unchanged", again["unchanged"], 3)
    check("stored", again["stored"], 0)
    check("removed", again["removed"], 0)

    print("\n3. one file edited, one file gone, prune on")
    third = client.post(
        "/ext/agents/sync",
        json={
            "machine": "Smoke-Box.local",
            "project": "Brown-Bear",
            "tool": "claude",
            "prune": True,
            "files": [
                {"path": "settings.json", "content": json.dumps({"model": "claude-sonnet-5"})},
                {"path": "CLAUDE.md", "content": "# rules\nbe brief\n"},
            ],
        },
    ).json()
    check("updated", third["updated"], 1)
    check("unchanged", third["unchanged"], 1)
    check("removed", third["removed"], 1)

    print("\n4. a second branch on the same machine — the global scope, a different tool")
    other = client.post(
        "/ext/agents/sync",
        json={
            "machine": "Smoke-Box.local",
            "scope": "global",
            "tool": "qwen",
            "prune": True,
            "files": [{"path": "settings.json", "content": "{}"}],
        },
    ).json()
    check("branch", other["branch"], "smoke-box.local/global/qwen")
    check("the project branch was untouched", other["removed"], 0)

    print("\n5. the branch listing")
    branch_params = {
        "machine": "smoke-box.local",
        "scope": "project",
        "project": "brownbear",
        "tool": "claude",
    }
    listing = client.get("/ext/agents/files", params=branch_params).json()
    check("files in the branch", listing["total"], 3)
    statuses = sorted(f"{f['path']}:{f['status']}" for f in listing["files"])
    check(
        "one is removed, two are synced",
        statuses,
        ["CLAUDE.md:synced", "settings.json:synced", "settings.local.json:removed"],
    )
    check("no content in the list", any("content" in f for f in listing["files"]), False)

    print("\n6. one file's stored content")
    target = next(f for f in listing["files"] if f["path"] == "settings.local.json")
    detail = client.get(f"/ext/agents/files/{target['config_id']}").json()
    check("redactions recorded", detail["redactions"], 1)
    check("the key is not in the stored content", "sk-ant" in (detail["content"] or ""), False)
    check("it is masked instead", "«redacted»" in (detail["content"] or ""), True)
    check("last content is kept for a removed file", detail["status"], "removed")

    print("\n7. the edited file's revision")
    edited = next(f for f in listing["files"] if f["path"] == "settings.json")
    check("revision counts distinct contents", edited["revision"], 2)

    print("\n8. the inventory tree")
    tree = client.get("/ext/agents").json()
    check("machines", tree["totals"]["machines"], 1)
    check("files", tree["totals"]["files"], 4)
    check("removed", tree["totals"]["removed"], 1)
    machine = tree["machines"][0]
    check("scope labels", [s["label"] for s in machine["scopes"]], ["Global", "brownbear"])
    check("global tool", machine["scopes"][0]["tools"][0]["tool"], "qwen")
    check("project tool", machine["scopes"][1]["tools"][0]["tool"], "claude")

    print("\n9. a zip sync")
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("skills/run/SKILL.md", b"# run\n")
        archive.writestr("agents/plan.md", b"# plan\n")
        archive.writestr("../escape.md", b"nope")
    zipped = client.post(
        "/ext/agents/sync/archive",
        files={"archive": ("claude.zip", buffer.getvalue(), "application/zip")},
        data={
            "machine": "Smoke-Box.local",
            "scope": "project",
            "project": "Brown-Bear",
            "tool": "claude",
        },
    ).json()
    check("stored from the archive", zipped["stored"], 2)
    check("the traversing entry was skipped", zipped["skipped"], 1)
    # prune defaults to false on the API, so the earlier files are still there.
    check("no reconciliation without prune", zipped["removed"], 0)

    print("\n10. delete purges the row")
    purge = client.delete(f"/ext/agents/files/{edited['config_id']}").json()
    check("deleted", purge["deleted"], True)
    check("gone", client.get(f"/ext/agents/files/{edited['config_id']}").status_code, 404)
    after = client.get("/ext/agents/files", params=branch_params).json()
    check("one fewer file in the branch", after["total"], 4)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("every check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
