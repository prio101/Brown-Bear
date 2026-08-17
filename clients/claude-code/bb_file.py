#!/usr/bin/env python3
"""Send a file to Brown Bear with the text extracted from it (spec 007).

Extraction happens HERE, on the machine that has the file. Brown Bear stores the
bytes and the text it is handed; it runs no OCR, no PDF parser and no vision model.
This script is the half of that contract that lives on the client.

    python3 bb_file.py notes.md
    python3 bb_file.py scan.pdf --project brown-bear --tags ops,retention
    python3 bb_file.py shot.png --extract-cmd 'tesseract {path} - 2>/dev/null'

Standard library only, like bb_context.py and bb_exchange.py — no pip install, and
deliberately not jq, which is not installed everywhere and would make the hook look
configured while silently doing nothing.

Configuration (environment):
  BB_GATEWAY_URL   required, https://brownbear.frostmangobox.com
  BB_EDGE_TOKEN    required, the shared edge secret
  BB_PROJECT       cache scope; defaults to the git repo name
  BB_EXTRACT_CMD   command template for extraction. `{path}` is substituted.
                   Chosen per machine, which is the point: one box has pdftotext,
                   another tesseract, another a local vision model, and none of
                   them need this script changed.

Nothing is uploaded if the content is already stored — the digest is checked first,
so a 40 MB PDF another machine already sent is never sent twice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# Cloudflare rejects the default Python-urllib User-Agent with 403 (error 1010,
# browser-integrity check), and these hooks fail open and silent — so without this
# every lookup on a remote machine returns nothing and never says why. Any
# identifiable agent string is accepted; this one names the client.
USER_AGENT = "brown-bear-client/1.0"

TIMEOUT = float(os.environ.get("BB_FILE_TIMEOUT", "120"))

#: Extractors tried when BB_EXTRACT_CMD is unset. First one present on PATH wins.
#: Text formats are read directly rather than shelled out to.
DEFAULT_EXTRACTORS: dict[str, tuple[str, ...]] = {
    "application/pdf": ("pdftotext -layout {path} -", "pdftotext {path} -"),
    "image/png": ("tesseract {path} - --psm 3",),
    "image/jpeg": ("tesseract {path} - --psm 3",),
    "image/webp": ("tesseract {path} - --psm 3",),
}

TEXTUAL_SUFFIXES = {".txt", ".md", ".markdown", ".json", ".csv", ".yaml", ".yml", ".toml", ".rst"}


def digest_of(path: Path) -> str:
    """Streamed, so hashing a large file does not load it into memory."""
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def which(command: str) -> bool:
    binary = shlex.split(command)[0]
    return any((Path(d) / binary).is_file() for d in os.environ.get("PATH", "").split(os.pathsep))


def extract(path: Path, media_type: str, override: str | None) -> tuple[str, str]:
    """Return (text, extractor_label).

    A failed or missing extractor is not an error: the file is still worth storing.
    It arrives with no text, Brown Bear marks it `stored` rather than `indexed`, and
    it is downloadable and visible while not being searchable. That is strictly
    better than refusing the upload.
    """
    if path.suffix.lower() in TEXTUAL_SUFFIXES or media_type.startswith("text/"):
        try:
            return path.read_text(encoding="utf-8", errors="replace"), "read directly"
        except OSError as exc:
            return "", f"unreadable: {exc}"

    candidates = (override,) if override else DEFAULT_EXTRACTORS.get(media_type, ())
    for template in candidates:
        if not template:
            continue
        command = template.replace("{path}", shlex.quote(str(path)))
        if not override and not which(command):
            continue
        try:
            done = subprocess.run(
                command, shell=True, capture_output=True, timeout=TIMEOUT, check=False
            )
        except subprocess.TimeoutExpired:
            continue
        text = done.stdout.decode("utf-8", errors="replace").strip()
        if text:
            return text, shlex.split(command)[0]
    return "", "none available"


def api(url: str, token: str, path: str) -> dict:
    request = urllib.request.Request(
        f"{url}{path}", headers={"Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def multipart(fields: dict[str, str], file_field: tuple[str, str, bytes]) -> tuple[bytes, str]:
    """Build a multipart body by hand.

    `requests` is not available and must not be required. The format is simple
    enough that hand-building it is less risk than adding a dependency to a script
    whose whole promise is that it runs on a bare Python.
    """
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
    return "default"


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a file and its extraction to Brown Bear.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--project", default=None)
    parser.add_argument("--source", default=None, help="retrieval label; defaults to the filename")
    parser.add_argument("--tags", default="")
    parser.add_argument("--extract-cmd", default=os.environ.get("BB_EXTRACT_CMD"))
    parser.add_argument("--force", action="store_true", help="upload even if already stored")
    args = parser.parse_args()

    url = (os.environ.get("BB_GATEWAY_URL") or "").rstrip("/")
    token = os.environ.get("BB_EDGE_TOKEN") or ""
    if not url or not token:
        print("BB_GATEWAY_URL and BB_EDGE_TOKEN must be set", file=sys.stderr)
        return 2
    if not args.path.is_file():
        print(f"not a file: {args.path}", file=sys.stderr)
        return 2

    digest = digest_of(args.path)
    media_type = mimetypes.guess_type(args.path.name)[0] or "application/octet-stream"

    if not args.force:
        try:
            state = api(url, token, f"/ext/files/{digest}/exists")
            if state.get("exists") and state.get("indexed"):
                print(f"already stored and indexed: {state['file_id']} ({state['chunk_count']} chunks)")
                return 0
        except urllib.error.HTTPError as exc:
            print(f"precheck failed ({exc.code}); uploading anyway", file=sys.stderr)
        except OSError as exc:
            print(f"precheck failed ({exc}); uploading anyway", file=sys.stderr)

    text, extractor = extract(args.path, media_type, args.extract_cmd)
    if not text:
        print(f"no text extracted ({extractor}) — uploading bytes only", file=sys.stderr)

    body, content_type = multipart(
        {
            "project": args.project or project_default(),
            "source": args.source or args.path.name,
            "sha256": digest,
            "extraction": text,
            "extractor": extractor,
            "extracted_by": os.uname().nodename,
            "tags": args.tags,
        },
        ("file", args.path.name, args.path.read_bytes()),
    )

    request = urllib.request.Request(
        f"{url}/ext/files",
        data=body,
        headers={"Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT, "Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        print(f"upload failed ({exc.code}): {exc.read().decode()[:300]}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"upload failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"{result['file_id']}  {result['status']}  "
        f"{result['chunks_stored']} chunks  extractor={extractor}"
        + ("  (deduplicated)" if result.get("deduplicated") else "")
    )
    for duplicate in result.get("near_duplicates") or []:
        print(f"  possible duplicate of {duplicate['source']} ({duplicate['score']:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
