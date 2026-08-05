#!/usr/bin/env python3
"""Assert the declared API contract matches the edge config (spec 006 §6.5).

`brownbear/api_contract.py` is a second source of truth beside
`edge/nginx.conf.template`, and a second source of truth rots. This derives
reachability from the nginx config and compares it to the declaration, so a route
published at the edge without being documented — or documented without being
published — fails here.

    python3 scripts/check_edge_contract.py          # exits non-zero on drift

**Why this is a script and not a pytest case.** The test suite runs inside an
image built from `jungle/app`, and Docker cannot COPY from outside its build
context, so `edge/nginx.conf.template` is not available in there. Rather than ship
a test that silently skips — which is worse than no test, because it looks like
coverage — the cross-file check lives here and runs on the host. The suite keeps
the checks it *can* enforce: that every OpenAPI path is declared, and that the page
leaks nothing.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EDGE = REPO / "edge" / "nginx.conf.template"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from brownbear.api_contract import CONTRACT, Reach  # noqa: E402


@dataclass(frozen=True)
class Location:
    raw: str
    kind: str  # "exact" | "regex" | "prefix"
    pattern: str
    reach: Reach
    methods: set[str] | None  # None means all methods


def parse_edge(text: str) -> list[Location]:
    """Extract every `location` block with its guard and method pin.

    Comment lines are stripped first: the config explains itself in prose that
    contains paths, and a naive parse picks those up as directives.
    """
    stripped = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )

    locations: list[Location] = []
    for match in re.finditer(r"location\s+([^{]+?)\s*\{(.*?)\n    \}", stripped, re.S):
        raw, body = match.group(1).strip(), match.group(2)
        if raw.startswith("@"):
            continue

        if raw.startswith("= "):
            kind, pattern = "exact", raw[2:].strip()
        elif raw.startswith("~ ") or raw.startswith("~* "):
            kind, pattern = "regex", raw.split(None, 1)[1].strip()
        else:
            kind, pattern = "prefix", raw

        if "return 403" in body:
            reach = Reach.DENIED
        elif "$bb_auth" in body:
            reach = Reach.AUTHENTICATED
        else:
            reach = Reach.PUBLIC

        pin = re.search(r"limit_except\s+([A-Z]+)", body)
        methods = {pin.group(1)} if pin else None

        locations.append(Location(raw, kind, pattern, reach, methods))
    return locations


def resolve(path: str, method: str, locations: list[Location]) -> Reach:
    """Approximate nginx matching: exact, then regex in order, then longest prefix.

    Good enough for this config, which uses only those three forms and no `^~`.
    """
    for loc in locations:
        if loc.kind == "exact" and loc.pattern == path:
            return _apply_method(loc, method)

    for loc in locations:
        if loc.kind == "regex" and re.search(loc.pattern, path):
            return _apply_method(loc, method)

    best: Location | None = None
    for loc in locations:
        if loc.kind == "prefix" and path.startswith(loc.pattern):
            if best is None or len(loc.pattern) > len(best.pattern):
                best = loc
    if best is not None:
        return _apply_method(best, method)

    return Reach.DENIED


def _apply_method(loc: Location, method: str) -> Reach:
    # `limit_except GET { deny all; }` returns 403 for anything else, so a
    # method-mismatched request is denied regardless of the location's guard.
    if loc.methods is not None and method.upper() not in loc.methods:
        return Reach.DENIED
    return loc.reach


def main() -> int:
    if not EDGE.exists():
        print(f"cannot find {EDGE}", file=sys.stderr)
        return 1

    locations = parse_edge(EDGE.read_text())
    print(f"parsed {len(locations)} locations from {EDGE.relative_to(REPO)}\n")

    failures = 0
    for endpoint in CONTRACT:
        # A templated path is documented by its literal form; nginx sees the
        # concrete request, so substitute something representative.
        probe = endpoint.path.replace("{slug}", "design-book.md")
        derived = resolve(probe, endpoint.method, locations)
        if derived is not endpoint.reach:
            failures += 1
            print(
                f"  DRIFT  {endpoint.method:<6} {endpoint.path:<34} "
                f"declared={endpoint.reach.value:<14} edge={derived.value}"
            )

    if failures:
        print(f"\n{failures} endpoint(s) disagree with the edge config")
        return 1

    print(f"all {len(CONTRACT)} declared endpoints agree with the edge config")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
