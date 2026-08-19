#!/usr/bin/env python3
"""Send a file and its reading to Brown Bear (spec 009).

    PostToolUse hook   python3 bb_media.py hook      < event.json
    send the bytes     python3 bb_media.py store handbook.pdf
    send the reading   python3 bb_media.py attach f_<id> --text-file english.txt \
                           --source-text-file original.txt --source-language ja

**Claude does the reading; this only moves data.** It runs no OCR, no PDF parser
and no translator — there is none on the machine and none in the stack worth
trusting (the gateway's Ollama has a 135M model pulled, which would produce a
confident mistranslation, and a confident mistranslation is worse than none).
Claude has already read the file natively by the time this runs, so the extraction
and the English translation are its job, and this ships the result.

The flow the hook sets up:

    Claude reads report-ja.pdf
      → hook: sha256, ask /ext/files/{sha}/exists
          already indexed → say so, ask for nothing, stop
          not stored      → POST /ext/files with the BYTES ONLY (status=stored)
      → hook injects the file_id and the exact command to send the text
      → Claude writes the English text (and keeps the original), runs `attach`
      → POST /ext/files/{id}/extraction → indexed, retrievable, translation kept

The bytes go up first and unconditionally, so a file that Claude never gets around
to describing is still stored, downloadable and visible on /files — the same
"stored beats lost" rule spec 007 already applies to a missing extractor.

Standard library only, like the other hooks. Fails open: every failure path exits 0
with no output, because a storage problem must never break a tool call.

Configuration — environment, then ~/.claude/bb/config.env:
  BB_GATEWAY_URL       required
  BB_EDGE_TOKEN        required
  BB_ENABLED           0 disables this hook without touching settings.json
  BB_PROJECT           corpus scope; defaults to the git repo name
  BB_MEDIA_MAX_BYTES   skip files larger than this (default 50 MB, the server cap)
  BB_MEDIA_TIMEOUT     seconds for a request (default 60)
  BB_MEDIA_TYPES       comma-separated extra extensions to treat as media
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# Cloudflare rejects the default Python-urllib User-Agent with 403 (error 1010,
# browser-integrity check), and these hooks fail open and silent — so without this
# every call from a remote machine does nothing and never says why.
USER_AGENT = "brown-bear-client/1.0"

CONFIG_FILE = Path.home() / ".claude" / "bb" / "config.env"

#: What counts as "a file worth reading into the memory".
#:
#: An allowlist, and for the same reason bb_sync.py uses one: this hook fires on
#: every Read, and Claude reads source files constantly. Uploading those would fill
#: the corpus with code that is already in the repository, and bury the documents
#: that are only readable as pictures.
MEDIA_SUFFIXES = frozenset(
    {
        ".pdf", ".epub",
        ".png", ".jpg", ".jpeg", ".webp", ".gif", ".tiff", ".tif", ".bmp", ".heic",
        ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
        ".odt", ".ods", ".odp", ".rtf", ".pages", ".numbers", ".key",
    }
)

DEFAULT_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_TIMEOUT = 60.0


def load_config() -> None:
    """Environment first, then ~/.claude/bb/config.env.

    The token lives in a file rather than in settings.json, which is synced,
    committed and pasted into issues. Environment wins so a single session can
    point at a different instance without editing anything.
    """
    if not CONFIG_FILE.is_file():
        return
    try:
        for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        pass


def gateway() -> tuple[str, str] | None:
    url = (os.environ.get("BB_GATEWAY_URL") or "").rstrip("/")
    token = os.environ.get("BB_EDGE_TOKEN") or ""
    if not url or not token:
        return None
    if (os.environ.get("BB_ENABLED") or "1").strip() in ("0", "false", "no"):
        return None
    return url, token


def timeout() -> float:
    try:
        return float(os.environ.get("BB_MEDIA_TIMEOUT") or DEFAULT_TIMEOUT)
    except ValueError:
        return DEFAULT_TIMEOUT


def max_bytes() -> int:
    try:
        return int(os.environ.get("BB_MEDIA_MAX_BYTES") or DEFAULT_MAX_BYTES)
    except ValueError:
        return DEFAULT_MAX_BYTES


def is_media(path: Path) -> bool:
    extra = {
        s if s.startswith(".") else f".{s}"
        for s in (os.environ.get("BB_MEDIA_TYPES") or "").lower().split(",")
        if s.strip()
    }
    return path.suffix.lower() in (MEDIA_SUFFIXES | extra)


def digest_of(path: Path) -> str:
    """Streamed, so hashing a 40 MB PDF does not load it into memory."""
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def project_for(cwd: str | None) -> str:
    """One corpus scope per repository, matching the other hooks exactly."""
    if override := os.environ.get("BB_PROJECT"):
        return override
    try:
        root = subprocess.run(
            ["git", "-C", str(cwd or os.getcwd()), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if root.returncode == 0 and root.stdout.strip():
            return Path(root.stdout.strip()).name
    except (OSError, subprocess.SubprocessError):
        pass
    return "default"


# --- transport --------------------------------------------------------------


def request(url: str, token: str, path: str, *, data: bytes | None = None,
            content_type: str | None = None, method: str = "GET") -> dict | None:
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(f"{url}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout()) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 404 on the extraction route means an older server that has not been
        # upgraded — the caller falls back to a full re-upload rather than failing.
        return {"_status": exc.code, "_detail": exc.read().decode("utf-8", "replace")[:300]}
    except (OSError, ValueError):
        return None


def multipart(fields: dict[str, str], file_field: tuple[str, str, bytes]) -> tuple[bytes, str]:
    """Hand-built: `requests` is not available and must not be required."""
    boundary = f"----bb{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    name, filename, payload = file_field
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode()
    )
    parts.append(payload)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def upload_bytes(url: str, token: str, path: Path, *, project: str,
                 extraction: str = "", extractor: str = "") -> dict | None:
    body, content_type = multipart(
        {
            "project": project,
            "source": path.name,
            "sha256": digest_of(path),
            "extraction": extraction,
            "extractor": extractor,
            "extracted_by": os.uname().nodename,
            "tags": "auto-ingest",
        },
        ("file", path.name, path.read_bytes()),
    )
    return request(url, token, "/ext/files", data=body, content_type=content_type, method="POST")


# --- commands ---------------------------------------------------------------


def cmd_store(args) -> int:
    load_config()
    creds = gateway()
    if creds is None:
        print("BB_GATEWAY_URL and BB_EDGE_TOKEN must be set", file=sys.stderr)
        return 2
    url, token = creds
    path = Path(args.path)
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 2

    result = upload_bytes(url, token, path, project=args.project or project_for(None))
    if not result or result.get("_status"):
        print(f"upload failed: {(result or {}).get('_detail', 'unreachable')}", file=sys.stderr)
        return 1
    print(f"{result['file_id']}  {result['status']}  {result.get('chunks_stored', 0)} chunks")
    return 0


def cmd_attach(args) -> int:
    load_config()
    creds = gateway()
    if creds is None:
        print("BB_GATEWAY_URL and BB_EDGE_TOKEN must be set", file=sys.stderr)
        return 2
    url, token = creds

    text = read_text(args.text_file, allow_stdin=True)
    if not text.strip():
        print("nothing to attach: the extraction is empty", file=sys.stderr)
        return 2
    source_text = read_text(args.source_text_file, allow_stdin=False)

    payload = {
        "text": text,
        "source_text": source_text or None,
        "language": args.language,
        "source_language": args.source_language,
        "extractor": args.extractor,
        "extracted_by": os.uname().nodename,
        "tags": args.tags,
    }
    result = request(
        url, token, f"/ext/files/{args.file_id}/extraction",
        data=json.dumps(payload).encode(), content_type="application/json", method="POST",
    )

    if result and result.get("_status") == 404 and args.file:
        # An older Brown Bear without the extraction route. Re-send the bytes with
        # the text attached, which every version since spec 007 accepts. Costs the
        # transfer again; keeps a mixed-version fleet working.
        #
        # One behavioural difference, worth knowing rather than discovering: the old
        # endpoint indexes whatever `extraction` it is given, so on this path BOTH
        # languages are embedded. The extraction route indexes the English half only.
        # Retrieval is therefore slightly noisier against an un-upgraded server, and
        # nothing is lost either way.
        print("server has no extraction route; re-sending with the bytes", file=sys.stderr)
        combined = text if not source_text else (
            f"{text}\n\n--- original ({args.source_language or 'source language'}), "
            f"as read by {args.extractor or 'an unnamed reader'} ---\n{source_text}"
        )
        result = upload_bytes(
            url, token, Path(args.file),
            project=args.project or project_for(None),
            extraction=combined,
            extractor=args.extractor or "",
        )

    if not result or result.get("_status"):
        print(f"attach failed: {(result or {}).get('_detail', 'unreachable')}", file=sys.stderr)
        return 1

    print(
        f"{result.get('file_id')}  {result.get('status')}  "
        f"{result.get('chunks_stored', 0)} chunks"
        + (f"  (replaced {result['chunks_removed']})" if result.get("chunks_removed") else "")
        + ("  translated" if result.get("translated") else "")
    )
    return 0


def read_text(source: str | None, *, allow_stdin: bool) -> str:
    if not source:
        return ""
    if source == "-" and allow_stdin:
        return sys.stdin.read()
    try:
        return Path(source).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"could not read {source}: {exc}", file=sys.stderr)
        return ""


# --- the hook ---------------------------------------------------------------


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj))


def instruction(file_id: str, path: Path, already_stored: bool) -> str:
    """What Claude is asked to do with the file it has just read.

    Deliberately explicit about the command, because the whole point of the split
    is that the reading happens here rather than on the server: Brown Bear stores
    text and cannot produce it.
    """
    hook_path = Path(__file__).resolve()
    return (
        f"`{path.name}` is stored in Brown Bear as `{file_id}`"
        + (" (bytes only — no text attached yet)." if not already_stored else ".")
        + "\n\nBrown Bear extracts nothing itself, so the reading is yours. If this file is "
        "worth remembering:\n"
        "1. Write out its text content **in English**. If the original is in another "
        "language, translate it, and keep the original text as well.\n"
        "2. Send both:\n"
        f"```bash\npython3 {hook_path} attach {file_id} \\\n"
        "  --text-file <english.txt> \\\n"
        "  --source-text-file <original.txt> --source-language <iso code> \\\n"
        f'  --extractor "<the model id you are>" --file {path}\n```\n'
        "Use `--text-file -` to pipe the English text on stdin instead. Omit the "
        "`--source-*` arguments when the document is already English.\n"
        "Skip all of this for a file that is noise — a screenshot of a terminal, an "
        "icon, a scratch export. Nothing here is automatic on purpose."
    )


def cmd_hook(_args) -> int:
    raw = sys.stdin.read()
    load_config()
    creds = gateway()
    if creds is None:
        return 0
    url, token = creds

    try:
        event = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return 0
    if not isinstance(event, dict):
        return 0

    tool_input = event.get("tool_input") or {}
    raw_path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not raw_path:
        return 0
    path = Path(str(raw_path))
    if not path.is_file() or not is_media(path):
        return 0

    try:
        size = path.stat().st_size
    except OSError:
        return 0
    if size == 0 or size > max_bytes():
        return 0

    digest = digest_of(path)
    state = request(url, token, f"/ext/files/{digest}/exists")
    if state is None or state.get("_status"):
        return 0  # gateway unwell: say nothing, cost nothing

    if state.get("indexed"):
        # Already read once. Asking again would re-embed a document for no gain.
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": (
                        f"`{path.name}` is already in Brown Bear as "
                        f"`{state.get('file_id')}` with {state.get('chunk_count')} indexed "
                        "chunks, so its text is retrievable. Nothing to send."
                    ),
                }
            }
        )
        return 0

    file_id = state.get("file_id")
    if not state.get("exists"):
        result = upload_bytes(url, token, path, project=project_for(event.get("cwd")))
        if not result or result.get("_status"):
            return 0
        file_id = result.get("file_id")
    if not file_id:
        return 0

    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": instruction(file_id, path, bool(state.get("exists"))),
            },
            "systemMessage": f"Brown Bear stored {path.name} ({file_id}) — text not attached yet",
        }
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a file and its reading to Brown Bear.")
    sub = parser.add_subparsers(dest="command", required=True)

    hook = sub.add_parser("hook", help="PostToolUse handler; reads the event on stdin")
    hook.set_defaults(func=cmd_hook)

    store = sub.add_parser("store", help="send a file's bytes, with no text")
    store.add_argument("path")
    store.add_argument("--project", default=None)
    store.set_defaults(func=cmd_store)

    attach = sub.add_parser("attach", help="send the text read out of an already-stored file")
    attach.add_argument("file_id")
    attach.add_argument("--text-file", required=True, help="English text; - for stdin")
    attach.add_argument("--source-text-file", default=None, help="the original language")
    attach.add_argument("--language", default="en")
    attach.add_argument("--source-language", default=None)
    attach.add_argument("--extractor", default=None, help="who read it, e.g. claude-opus-5")
    attach.add_argument("--tags", default=None)
    attach.add_argument("--project", default=None)
    attach.add_argument("--file", default=None, help="the original path, for the re-upload fallback")
    attach.set_defaults(func=cmd_attach)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 — a hook crash must never break a tool call
        sys.exit(0)
