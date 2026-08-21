#!/usr/bin/env python3
"""Brown Bear context gateway — Claude Code Stop hook.

Runs when Claude finishes a turn. Posts the completed exchange so the answer is
available to the semantic cache next time, and reports token usage — spec 003's
M8, since the client is the only party that saw the response.

FAILS OPEN AND SILENT. A storage failure must never disturb a finished turn.

Configuration (environment) — as bb_context.py, plus:
  BB_STORE_MIN_CHARS  skip answers shorter than this (default 200). "Done." is
                      noise in a cache; its usage is still reported.
  BB_NO_STORE         1 = report usage only, never store the exchange.
  BB_MACHINE          name to attribute this machine's prompts to in the Prompt
                      Palace (default: this host's name).

Transcript parsing is defensive: field names are checked rather than assumed.
Run once with BB_HOOK_DEBUG=1 and read $TMPDIR/bb-hook-input.jsonl to see the
real payload if nothing is landing.
"""

import hashlib
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Cloudflare rejects the default Python-urllib User-Agent with 403 (error 1010,
# browser-integrity check), and these hooks fail open and silent — so without this
# every lookup on a remote machine returns nothing and never says why. Any
# identifiable agent string is accepted; this one names the client.
USER_AGENT = "brown-bear-client/1.0"

TIMEOUT_DEFAULT = 10.0
MIN_CHARS_DEFAULT = 200


def machine_name() -> str:
    """This box's name, for attributing the exchange (spec 012).

    A memory shared between machines is much less useful if you cannot tell which
    machine asked. `os.uname()` is what bb_file.py uses for `extracted_by`, but it
    does not exist on Windows, and this hook must never raise inside a finished
    turn — so `socket.gethostname()` is the fallback. Sent as a claim: the edge
    authenticates one shared secret for every machine and cannot check it.

    BB_MACHINE overrides it, for a box whose hostname is meaningless (a container
    id, or a laptop called `localhost`).
    """
    override = (os.environ.get("BB_MACHINE") or "").strip()
    if override:
        return override[:128]
    try:
        return (os.uname().nodename or socket.gethostname())[:128]
    except (AttributeError, OSError):
        try:
            return socket.gethostname()[:128]
        except OSError:
            return ""


def debug_dump(raw: str) -> None:
    if not os.environ.get("BB_HOOK_DEBUG"):
        return
    try:
        target = Path(os.environ.get("TMPDIR", "/tmp")) / "bb-hook-input.jsonl"
        with target.open("a", encoding="utf-8") as handle:
            handle.write(raw.rstrip("\n") + "\n")
    except OSError:
        pass


def project_for(event: dict) -> str:
    """Must match bb_context.py exactly, or lookups never find what was stored.

    Outside a repository this is "default", not the directory's name -- see the
    long form in bb_context.py and BB-202.
    """
    override = os.environ.get("BB_PROJECT")
    if override:
        return override

    cwd = event.get("cwd") or os.getcwd()
    try:
        root = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if root.returncode == 0 and root.stdout.strip():
            return Path(root.stdout.strip()).name
    except (OSError, subprocess.SubprocessError):
        pass
    return "default"


def text_of(message: dict) -> str:
    """Flatten message content, which may be a string or a list of blocks."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(part for part in parts if part)
    return ""


def read_transcript(path: Path) -> dict:
    """Last real user prompt, last assistant answer, and that answer's usage."""
    last_user = ""
    last_assistant = ""
    usage: dict = {}
    model = ""

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or event.get("isMeta"):
                    continue

                kind = event.get("type")
                message = event.get("message")
                if not isinstance(message, dict):
                    continue

                if kind == "user":
                    text = text_of(message)
                    # Tool results arrive as user events with no text blocks;
                    # those are not prompts.
                    if text.strip():
                        last_user = text
                elif kind == "assistant":
                    text = text_of(message)
                    if text.strip():
                        last_assistant = text
                    if isinstance(message.get("usage"), dict):
                        usage = message["usage"]
                    if message.get("model"):
                        model = str(message["model"])
    except OSError:
        return {}

    # Input tokens arrive in three buckets that are NOT billed alike: fresh
    # input and cache *writes* cost roughly full rate, cache *reads* about a
    # tenth. Brown Bear prices a model at one input rate, so summing all three
    # overstates cost badly for a cache-heavy session — a long Claude Code turn
    # can be 2 fresh tokens against 200k cache reads.
    #
    # Default to the true total, because this is a usage tracker and that is the
    # real volume. Set BB_EXCLUDE_CACHE_READS=1 to report only the tokens billed
    # near full rate, which tracks cost far more closely.
    def bucket(key: str) -> int:
        value = usage.get(key)
        return value if isinstance(value, int) else 0

    fresh = bucket("input_tokens")
    cache_write = bucket("cache_creation_input_tokens")
    cache_read = bucket("cache_read_input_tokens")

    # BB_EXCLUDE_CACHE_READS is now a blunt instrument kept only for compatibility.
    # It used to be the only defence against cache reads being priced at the full
    # input rate; the server now prices each bucket at its own rate, so dropping
    # reads understates volume for no benefit.
    if os.environ.get("BB_EXCLUDE_CACHE_READS"):
        cache_read = 0

    output = usage.get("output_tokens")
    return {
        "prompt": last_user,
        "response": last_assistant,
        "tokens_in": fresh + cache_write + cache_read,
        "tokens_in_fresh": fresh,
        "tokens_cache_write": cache_write,
        "tokens_cache_read": cache_read,
        "tokens_out": output if isinstance(output, int) else 0,
        "model": model,
    }


def main() -> int:
    raw = sys.stdin.read()
    debug_dump(raw)

    url = (os.environ.get("BB_GATEWAY_URL") or "").rstrip("/")
    token = os.environ.get("BB_EDGE_TOKEN") or ""
    if not url or not token:
        return 0

    try:
        event = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return 0
    if not isinstance(event, dict):
        return 0

    transcript_path = event.get("transcript_path") or event.get("transcript")
    if not transcript_path:
        return 0
    path = Path(str(transcript_path))
    if not path.is_file():
        return 0

    turn = read_transcript(path)
    prompt = (turn.get("prompt") or "").strip()
    if not prompt:
        return 0

    response = turn.get("response") or ""
    try:
        min_chars = int(os.environ.get("BB_STORE_MIN_CHARS") or MIN_CHARS_DEFAULT)
    except ValueError:
        min_chars = MIN_CHARS_DEFAULT

    store = not os.environ.get("BB_NO_STORE") and len(response.strip()) >= min_chars

    # Dedup: replaying the same turn must not double-count usage.
    session = str(event.get("session_id") or "")
    digest = hashlib.sha256(f"{session}\x00{prompt}".encode("utf-8")).hexdigest()[:32]

    # BB_MODEL is authoritative, and must resolve identically here and in
    # bb_context.py: a cache hit is scoped to the same model, so if this hook
    # stored under the transcript's "claude-opus-5" while the lookup asked for
    # "claude", nothing would ever hit and the cache would look broken.
    # Set BB_MODEL to your real model id so scope agrees AND pricing resolves.
    model = os.environ.get("BB_MODEL") or "claude"

    body = {
        "prompt": prompt,
        "response": response if response.strip() else "(empty response)",
        "project": project_for(event),
        "model": model,
        "tokens_in": turn.get("tokens_in") or 0,
        # The breakdown is what the server prices from. Providers bill these three
        # at different rates — fresh at par, cache writes above it, cache reads at a
        # fraction — so sending only the sum overstates a cache-heavy session badly.
        "tokens_in_fresh": turn.get("tokens_in_fresh") or 0,
        "tokens_cache_write": turn.get("tokens_cache_write") or 0,
        "tokens_cache_read": turn.get("tokens_cache_read") or 0,
        "tokens_out": turn.get("tokens_out") or 0,
        "request_id": f"cc-{digest}",
        "store": store,
    }

    # Omitted rather than sent empty when the name cannot be determined: the
    # server records "not recorded", which is true, instead of an empty claim.
    if name := machine_name():
        body["machine"] = name

    try:
        timeout = float(os.environ.get("BB_TIMEOUT") or TIMEOUT_DEFAULT)
    except ValueError:
        timeout = TIMEOUT_DEFAULT

    request = urllib.request.Request(
        f"{url}/ext/exchange",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            reply.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
        return 0

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - a hook crash must never disturb the turn
        sys.exit(0)
