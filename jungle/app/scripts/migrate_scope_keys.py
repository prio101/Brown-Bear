#!/usr/bin/env python3
"""Re-key existing cache documents to normalised project scopes (BB-202).

Before the fix, the `project` metadata was whatever the client happened to send,
matched with Chroma `$eq`. `Brown-Bear` and `brownbear` were therefore two
mutually invisible caches. Lookups now normalise (lower-case, punctuation
stripped), so documents stored under an un-normalised key become unreachable
unless they are re-keyed — which is what this does.

Dry run by default. Nothing is written without --apply:

    python3 scripts/migrate_scope_keys.py                      # report only
    python3 scripts/migrate_scope_keys.py --apply

Not an Alembic migration: the data lives in ChromaDB, not PostgreSQL, and this
runs once by hand rather than on every deploy.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

CHROMA = "http://127.0.0.1:8000"
TENANT = "default_tenant"
DATABASE = "default_database"
COLLECTIONS = ("conversations", "knowledge")

# Must stay identical to gateway.normalise_project. Duplicated rather than
# imported so this script runs on the host without the app's dependencies; the
# test suite pins the real one, and any drift shows up as a no-op migration.
_NOISE = re.compile(r"[^a-z0-9]+")


def normalise_project(value: str) -> str:
    return _NOISE.sub("", value.strip().lower()) or "default"


def _post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{CHROMA}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    return json.loads(body) if body else {}


def _get(path: str) -> object:
    with urllib.request.urlopen(f"{CHROMA}{path}", timeout=30) as response:
        return json.loads(response.read())


def collection_ids() -> dict[str, str]:
    listed = _get(f"/api/v2/tenants/{TENANT}/databases/{DATABASE}/collections")
    return {c["name"]: c["id"] for c in listed if c.get("name") in COLLECTIONS}


def migrate(name: str, cid: str, apply: bool) -> tuple[int, int]:
    base = f"/api/v2/tenants/{TENANT}/databases/{DATABASE}/collections/{cid}"
    fetched = _post(f"{base}/get", {"limit": 10_000, "include": ["metadatas"]})
    ids = fetched.get("ids") or []
    metadatas = fetched.get("metadatas") or []

    changed_ids: list[str] = []
    changed_metadatas: list[dict] = []

    for doc_id, metadata in zip(ids, metadatas, strict=False):
        metadata = metadata or {}
        current = metadata.get("project")
        if not isinstance(current, str):
            continue
        canonical = normalise_project(current)
        if canonical == current:
            continue
        # Preserve the original spelling: it is the only record of where a
        # document actually came from, and re-keying is otherwise irreversible.
        updated = {**metadata, "project": canonical, "project_original": current}
        changed_ids.append(doc_id)
        changed_metadatas.append(updated)
        print(f"  {name}: {current!r} -> {canonical!r}  ({doc_id[:12]}…)")

    if changed_ids and apply:
        _post(f"{base}/update", {"ids": changed_ids, "metadatas": changed_metadatas})

    return len(ids), len(changed_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes")
    args = parser.parse_args()

    try:
        found = collection_ids()
    except (urllib.error.URLError, OSError) as exc:
        print(f"cannot reach ChromaDB at {CHROMA}: {exc}", file=sys.stderr)
        return 1

    if not found:
        print("no conversations/knowledge collection found — nothing to do")
        return 0

    total = rekeyed = 0
    for name, cid in sorted(found.items()):
        seen, changed = migrate(name, cid, args.apply)
        total += seen
        rekeyed += changed

    verb = "re-keyed" if args.apply else "would re-key"
    print(f"\n{verb} {rekeyed} of {total} documents")
    if rekeyed and not args.apply:
        print("re-run with --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
