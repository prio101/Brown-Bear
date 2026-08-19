#!/usr/bin/env python3
"""Sync this machine's agent configuration to Brown Bear (spec 008).

Walks a tool's configuration directory — `.claude/` in a checkout, or `~/.claude`
for the machine-wide one — and posts it under

    machine name  →  Global | project  →  tool  →  path

    python3 bb_sync.py                        # this repo's .claude, project scope
    python3 bb_sync.py --global                # ~/.claude, machine scope
    python3 bb_sync.py --tool qwen --global     # ~/.qwen
    python3 bb_sync.py --zip                   # send the directory as one archive
    python3 bb_sync.py --dry-run               # print what would be sent, send nothing

Standard library only, like the other hooks in this directory — no pip install.

Configuration (environment):
  BB_GATEWAY_URL   required, https://brownbear.frostmangobox.com
  BB_EDGE_TOKEN    required, the shared edge secret
  BB_MACHINE       what this machine calls itself; defaults to the hostname
  BB_PROJECT       project scope; defaults to the git repo name

**Two things are deliberately not sent.** Files whose only content is a credential
(`.credentials.json`, `.env`, `*.pem`) are never uploaded, and the session data that
lives beside the settings in `~/.claude` — `projects/`, `history/`, `todos/`,
`shell-snapshots/` — is excluded: it is conversation transcripts, not configuration,
and it is orders of magnitude larger.

**Redaction happens twice, and only the second time counts.** This script masks what
it recognises before sending, and the server masks again before writing the row. The
server's pass is the guarantee — this one is a courtesy, because an older copy of
this script, or a hand-rolled `curl`, would skip it entirely.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

# Cloudflare rejects the default Python-urllib User-Agent with 403 (error 1010,
# browser-integrity check). Any identifiable agent string is accepted.
USER_AGENT = "brown-bear-client/1.0"

TIMEOUT = float(os.environ.get("BB_SYNC_TIMEOUT", "120"))

#: Matches the server's cap. A larger file is skipped here rather than sent to be
#: recorded as `too_large`: the round trip buys nothing.
MAX_FILE_BYTES = 256 * 1024

#: What counts as configuration — an ALLOWLIST, and it has to be one.
#:
#: A denylist was tried first and lost: this machine's `~/.claude` holds 631 files,
#: of which about a dozen are configuration. The rest is runtime state that a
#: directory accretes over time — `plugins/repos` alone is 505 files of git clones,
#: `file-history/` is 125 snapshots, `projects/` is every conversation transcript.
#: A denylist has to be updated every time the tool grows a new cache directory,
#: and the failure mode is silent: megabytes of transcripts uploaded as "settings".
#:
#: Files matched by name at the top level of the directory.
CONFIG_FILES = frozenset(
    {
        "settings.json", "settings.local.json", "CLAUDE.md", "CLAUDE.local.md",
        "QWEN.md", "AGENTS.md", ".mcp.json", "mcp.json", "mcp_servers.json",
        "keybindings.json", "statusline-command.sh", "statusline.sh",
        "policy-limits.json", "output-style.json",
    }
)

#: Directories walked recursively, because their whole contents are configuration.
CONFIG_DIRS = frozenset(
    {"agents", "commands", "skills", "hooks", "output-styles", "rules", "prompts"}
)

#: Configuration that happens to live inside a directory which is otherwise state.
CONFIG_PATHS = frozenset({"plugins/config.json", "plugins/installed.json"})

#: Never descended into, even under an allowed directory: a skill with its own
#: checkout or `node_modules` would otherwise drag it all along.
NESTED_EXCLUDED = frozenset(
    {"repos", "node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build", ".next"}
)

#: Never uploaded whatever else matches. The server refuses these too; skipping
#: them here means they do not leave the machine at all.
EXCLUDED_NAMES = frozenset(
    {".credentials.json", "credentials.json", ".netrc", ".DS_Store", "id_rsa", "id_ed25519"}
)
EXCLUDED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".pyc", ".log", ".lock", ".bak")

MASK = "«redacted»"

#: The same shapes the server masks. Duplicated on purpose: this script imports
#: nothing from the server and must run on a bare Python, so the alternative to
#: duplication is no client-side redaction at all.
_PATTERNS = (
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
    re.compile(
        r"(?P<pre>^[A-Za-z0-9_.\-]*"
        r"(?:TOKEN|API[_-]?KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL)"
        r"[A-Za-z0-9_.\-]*\s*=\s*)\S{4,}$",
        re.IGNORECASE | re.MULTILINE,
    ),
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
_ENV_BLOCK = re.compile(r'("env"\s*:\s*\{)([^{}]*)(\})', re.IGNORECASE)
_ENV_VALUE = re.compile(r'(:\s*")([^"\\]{1,})(")')


def redact(text: str) -> tuple[str, int]:
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
        if MASK in match.group(0):
            return match.group(0)
        masked += 1
        return f"{match.group('pre')}{MASK}{match.groupdict().get('post') or ''}"

    for pattern in _PATTERNS:
        result = pattern.sub(_one, result)
    return result, masked


def excluded(relative: Path, *, everything: bool) -> str | None:
    """Why this path is not being sent, or None.

    A reason string rather than a boolean: an exclusion nobody can see is
    indistinguishable from a file that failed to upload, so every skip is
    printed with the reason it was skipped.
    """
    name = relative.name
    if name in EXCLUDED_NAMES:
        return "holds a credential"
    if name == ".env" or name.startswith(".env."):
        return "holds a credential"
    if name.endswith(EXCLUDED_SUFFIXES):
        return "not configuration"
    if any(part in NESTED_EXCLUDED for part in relative.parts):
        return f"inside {next(p for p in relative.parts if p in NESTED_EXCLUDED)}/"

    posix = relative.as_posix()
    if posix in CONFIG_PATHS:
        return None
    if everything:
        return None
    if len(relative.parts) == 1:
        return None if name in CONFIG_FILES else "not a known configuration file"
    if relative.parts[0] in CONFIG_DIRS:
        return None
    return f"{relative.parts[0]}/ is runtime state, not configuration"


def walk(root: Path, *, everything: bool) -> list[tuple[Path, str | None]]:
    """Every file under root, each with its exclusion reason or None."""
    found: list[tuple[Path, str | None]] = []
    for path in sorted(root.rglob("*")):
        # Symlinks are skipped rather than followed: a link out of the directory
        # would sync a file from somewhere else under this address.
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root)
        found.append((relative, excluded(relative, everything=everything)))
    return found


def pull(url: str, token: str, params: dict[str, str]) -> dict | None:
    query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items() if v != "")
    request = urllib.request.Request(
        f"{url}/ext/agents/pull?{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def restore(payload: dict, root: Path, *, apply: bool, force: bool) -> int:
    """Write a pulled branch back onto this machine.

    Three refusals, and each exists because the alternative is a file that looks
    right and is not:

      * **Never a file the server marked unrestorable.** A masked value written
        back verbatim produces a `settings.json` with `«redacted»` where an API key
        belongs. The server computes that verdict; this only obeys it.
      * **Never over a file whose content differs**, unless --force. Restoring is
        for a machine that lost something, not for silently reverting work.
      * **Nothing at all without --apply.** A restore that runs by accident is the
        one failure mode worse than no restore.
    """
    written = skipped = differing = 0
    for entry in payload.get("files", []):
        target = root / entry["path"]
        if not entry.get("restorable"):
            print(f"  refuse  {entry['path']}: {entry.get('reason')}")
            skipped += 1
            continue
        content = entry.get("content")
        if content is None:
            print(f"  refuse  {entry['path']}: no content stored")
            skipped += 1
            continue
        if target.is_file():
            current = target.read_text(encoding="utf-8", errors="replace")
            if current == content:
                print(f"  same    {entry['path']}")
                continue
            if not force:
                print(f"  differs {entry['path']}  (pass --force to overwrite)")
                differing += 1
                continue
        if apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            print(f"  wrote   {entry['path']}  (revision {entry.get('revision')})")
        else:
            print(f"  would write {entry['path']}  (revision {entry.get('revision')})")
        written += 1

    for entry in payload.get("excluded", []):
        print(f"  skip    {entry['path']}: {entry['reason']}")

    verb = "wrote" if apply else "would write"
    print(f"\n{verb} {written} file(s); {skipped} refused, {differing} differ")
    if not apply and written:
        print("nothing was written — re-run with --apply")
    return 0 if apply or not written else 0


def project_default() -> str:
    if value := os.environ.get("BB_PROJECT"):
        return value
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, timeout=5, check=False
        )
        if top.returncode == 0:
            return Path(top.stdout.decode().strip()).name
    except (OSError, subprocess.TimeoutExpired):
        pass
    return Path.cwd().name


def machine_default() -> str:
    return os.environ.get("BB_MACHINE") or os.uname().nodename


def post(url: str, token: str, path: str, body: bytes, content_type: str) -> dict:
    request = urllib.request.Request(
        f"{url}{path}",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
            "Content-Type": content_type,
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def multipart(fields: dict[str, str], file_field: tuple[str, str, bytes]) -> tuple[bytes, str]:
    """Hand-built, because `requests` is not available and must not be required."""
    import uuid

    boundary = f"----bb{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    name, filename, payload = file_field
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        f"Content-Type: application/zip\r\n\r\n".encode()
    )
    parts.append(payload)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync agent configuration to Brown Bear.")
    parser.add_argument("--tool", default="claude", choices=("claude", "qwen"))
    parser.add_argument(
        "--global", dest="is_global", action="store_true",
        help="sync ~/.<tool> as the machine-wide 'Global' scope instead of this checkout's",
    )
    parser.add_argument("--dir", type=Path, default=None, help="override the directory to walk")
    parser.add_argument("--machine", default=None)
    parser.add_argument("--project", default=None)
    parser.add_argument(
        "--zip", dest="as_zip", action="store_true",
        help="send one archive instead of a JSON body; carries binaries too",
    )
    parser.add_argument(
        "--no-prune", dest="prune", action="store_false",
        help="leave files that are no longer here alone, instead of marking them removed",
    )
    parser.add_argument(
        "--all", dest="everything", action="store_true",
        help="walk the whole directory instead of the known configuration files; "
             "on a global ~/.claude this includes conversation transcripts and caches",
    )
    parser.add_argument(
        "--pull", action="store_true",
        help="fetch this branch back from Brown Bear instead of sending it; prints "
             "what it would write unless --apply is given",
    )
    parser.add_argument("--apply", action="store_true", help="with --pull: actually write the files")
    parser.add_argument(
        "--force", action="store_true",
        help="with --pull --apply: overwrite a file whose content differs",
    )
    parser.add_argument("--include-removed", action="store_true",
                        help="with --pull: also restore files deleted from the machine")
    parser.add_argument("--dry-run", action="store_true")
    parser.set_defaults(prune=True)
    args = parser.parse_args()

    root = args.dir or (
        Path.home() / f".{args.tool}" if args.is_global else Path.cwd() / f".{args.tool}"
    )
    # Deliberately NOT checked before a pull: the case a restore exists for is a
    # machine that no longer has the directory. `restore` creates what it needs.

    machine_name = args.machine or machine_default()
    scope_name = "global" if args.is_global else "project"
    project_name = "" if args.is_global else (args.project or project_default())

    if args.pull:
        url = (os.environ.get("BB_GATEWAY_URL") or "").rstrip("/")
        token = os.environ.get("BB_EDGE_TOKEN") or ""
        if not url or not token:
            print("BB_GATEWAY_URL and BB_EDGE_TOKEN must be set", file=sys.stderr)
            return 2
        try:
            payload = pull(url, token, {
                "machine": machine_name,
                "scope": scope_name,
                "project": project_name,
                "tool": args.tool,
                "include_removed": "true" if args.include_removed else "",
            })
        except urllib.error.HTTPError as exc:
            print(f"pull failed ({exc.code}): {exc.read().decode()[:300]}", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"pull failed: {exc}", file=sys.stderr)
            return 1
        if not payload:
            print("pull returned nothing", file=sys.stderr)
            return 1
        print(f"{payload['branch']} → {root}")
        print(f"  {payload['restorable']} restorable, {payload['not_restorable']} not")
        return restore(payload, root, apply=args.apply, force=args.force)

    if not root.is_dir():
        print(f"no configuration directory at {root}", file=sys.stderr)
        return 2

    entries = walk(root, everything=args.everything)
    included = [(rel, reason) for rel, reason in entries if reason is None]
    skipped = [(rel, reason) for rel, reason in entries if reason is not None]

    payload: list[dict[str, str]] = []
    archive_buffer = io.BytesIO()
    archive = zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) if args.as_zip else None
    masked_total = 0

    for relative, _ in included:
        absolute = root / relative
        size = absolute.stat().st_size
        if size > MAX_FILE_BYTES:
            skipped.append((relative, f"{size} bytes, over the {MAX_FILE_BYTES} byte cap"))
            continue
        data = absolute.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            if archive is None:
                # A JSON body carries text. The archive route carries the bytes and
                # the server records them with no content, which is the honest
                # outcome for a binary — but there is no point sending it here.
                skipped.append((relative, "not text; use --zip to send it"))
                continue
            archive.writestr(relative.as_posix(), data)
            continue

        text, masked = redact(text)
        masked_total += masked
        if archive is None:
            payload.append({"path": relative.as_posix(), "content": text})
        else:
            archive.writestr(relative.as_posix(), text.encode("utf-8"))

    if archive is not None:
        archive.close()

    machine, scope, project = machine_name, scope_name, project_name
    count = len(payload) if archive is None else len(zipfile.ZipFile(io.BytesIO(archive_buffer.getvalue())).infolist())

    if args.dry_run:
        print(f"{root} → {machine}/{'global' if args.is_global else project}/{args.tool}")
        print(f"  would send {count} file(s), {masked_total} value(s) masked here")
        for relative, _ in included:
            print(f"    + {relative.as_posix()}")
        # Grouped by reason rather than listed: a global directory skips hundreds
        # of files, and 600 lines of output is the same as no output.
        grouped: dict[str, int] = {}
        for _, reason in skipped:
            grouped[reason] = grouped.get(reason, 0) + 1
        for reason, number in sorted(grouped.items(), key=lambda item: -item[1]):
            print(f"    - {number} file(s) skipped: {reason}")
        print("  nothing was sent (--dry-run)")
        return 0

    url = (os.environ.get("BB_GATEWAY_URL") or "").rstrip("/")
    token = os.environ.get("BB_EDGE_TOKEN") or ""
    if not url or not token:
        print("BB_GATEWAY_URL and BB_EDGE_TOKEN must be set", file=sys.stderr)
        return 2

    try:
        if archive is None:
            body = json.dumps(
                {
                    "machine": machine,
                    "scope": scope,
                    "project": project,
                    "tool": args.tool,
                    "prune": args.prune,
                    "files": payload,
                }
            ).encode()
            result = post(url, token, "/ext/agents/sync", body, "application/json")
        else:
            body, content_type = multipart(
                {
                    "machine": machine,
                    "scope": scope,
                    "project": project,
                    "tool": args.tool,
                    "prune": "true" if args.prune else "false",
                },
                ("archive", f"{args.tool}.zip", archive_buffer.getvalue()),
            )
            result = post(url, token, "/ext/agents/sync/archive", body, content_type)
    except urllib.error.HTTPError as exc:
        print(f"sync failed ({exc.code}): {exc.read().decode()[:300]}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"sync failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"{result['branch']}  {result['stored']} new  {result['updated']} changed  "
        f"{result['unchanged']} unchanged  {result['removed']} removed  {result['skipped']} skipped"
    )
    # The server's count, not this script's: it is the one that decided what was
    # written, and a difference between the two is worth seeing.
    if result.get("redactions"):
        print(f"  {result['redactions']} value(s) masked server-side before storage")
    for entry in result.get("files", []):
        if entry.get("outcome") == "skipped":
            print(f"  skipped {entry['path']}: {entry['reason']}")
    grouped: dict[str, int] = {}
    for _, reason in skipped:
        grouped[reason] = grouped.get(reason, 0) + 1
    for reason, number in sorted(grouped.items(), key=lambda item: -item[1]):
        print(f"  {number} file(s) not sent: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
