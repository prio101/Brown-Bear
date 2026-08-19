# Claude Code ↔ Brown Bear context gateway

Two hooks that put Brown Bear in front of Claude on any machine:

| Hook | Event | What it does |
|---|---|---|
| `bb_context.py` | `UserPromptSubmit` | Before each prompt: POSTs it to `/ext/context`, injects a cached answer or retrieved chunks |
| `bb_exchange.py` | `Stop` | After each turn: POSTs prompt + answer + token usage to `/ext/exchange` |
| `bb_media.py hook` | `PostToolUse` (`Read`) | When Claude reads a PDF, image or document: stores the bytes and asks Claude for the text in English |

Two commands you run yourself, rather than hooks: `bb_file.py` sends a file with
the text this machine extracted from it, and `bb_sync.py` sends this machine's
`.claude` / `.qwen` configuration. Both are documented at the end of this file,
along with `bb_media.py`, which is both a hook and a pair of commands.

Both **fail open and silent.** If the gateway is unreachable, unauthenticated,
slow, or returns junk, they exit 0 with no output and Claude proceeds normally.
Brown Bear being down degrades context; it never blocks your work.

## Read this first

**Every prompt and every answer leaves the machine.** The context hook sends
your prompt over the internet to Brown Bear; the Stop hook sends the prompt and
the full response, and stores them in ChromaDB by default. That is the point of
the feature, but decide deliberately.

The gateway is at a **permanent** hostname, `brownbear.frostmangobox.com`. That
is what makes a memory graph across machines workable, but be clear about the
trade: the address is now stable, guessable, and durably reachable, where a
`trycloudflare.com` URL was merely unlisted. Obscurity is no longer part of the
defence, so `BB_EDGE_TOKEN` is the whole of it — treat it as the only thing
standing between the internet and every prompt you have ever sent.

Use `BB_NO_STORE=1` to meter without storing, and `BB_STORE_MIN_CHARS` to keep
trivial answers out of the cache.

## Requirements

- `python3` (standard library only — no `pip install`, and deliberately **not**
  `jq`, which is not installed everywhere and would make the hooks look
  configured while silently doing nothing)
- `git` (optional; used only to name the cache scope)

## Install

### 1. Copy the scripts

On this machine they already live here. On a second machine:

```bash
mkdir -p ~/.claude/bb && cd ~/.claude/bb
# copy bb_context.py and bb_exchange.py here, then:
chmod +x bb_context.py bb_exchange.py
```

### 2. Set the environment

The hooks read their configuration from the environment, so the secret is never
written into `settings.json`. Put this in your shell profile
(`~/.zshrc`, `~/.bashrc`):

```bash
export BB_GATEWAY_URL="https://brownbear.frostmangobox.com"
export BB_EDGE_TOKEN="<the BB_EDGE_TOKEN from Brown Bear's .env>"
export BB_MODEL="claude-opus-5"     # see the warning below — set this
```

### 3. Wire the hooks

Add to `~/.claude/settings.json` for every project, or
`.claude/settings.local.json` for one project only. **Merge** with whatever
`hooks` block is already there rather than replacing it.

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/bb/bb_context.py",
            "timeout": 10,
            "statusMessage": "Asking Brown Bear for context..."
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/bb/bb_exchange.py",
            "timeout": 15,
            "async": true
          }
        ]
      }
    ]
  }
}
```

`async: true` on the Stop hook keeps storage off the critical path — you never
wait for Brown Bear after a turn finishes.

Open `/hooks` once afterwards (or restart Claude Code) so the config is picked
up; the settings watcher only watches directories that had a settings file when
the session started.

## `BB_MODEL` must be the same on every machine

A cache hit is scoped to the same `project` **and** the same `model`. Both hooks
resolve the model from `BB_MODEL` (default `"claude"`), so if one machine sets
`claude-opus-5` and another leaves it unset, **they will never share a cache
hit** — each stores under a different scope and neither finds the other's
answers.

Set it to your real model id: that makes the scope agree *and* lets Brown Bear
resolve pricing for the reported usage.

## Configuration reference

| Variable | Default | Meaning |
|---|---|---|
| `BB_GATEWAY_URL` | — | Gateway base URL, fixed at `https://brownbear.frostmangobox.com`. **Unset = hooks disabled** |
| `BB_EDGE_TOKEN` | — | Shared edge secret. **Unset = hooks disabled** |
| `BB_MODEL` | `claude` | Cache scope + pricing key. Keep identical everywhere |
| `BB_PROJECT` | git repo name | Cache scope. Defaults to the repository's directory name |
| `BB_TIMEOUT` | `6` / `10` | Seconds to wait before giving up and proceeding |
| `BB_CACHE_MODE` | `inject` | `inject` or `block` — see below |
| `BB_NO_STORE` | unset | `1` = report usage only, never store the exchange |
| `BB_STORE_MIN_CHARS` | `200` | Answers shorter than this are not cached |
| `BB_EXCLUDE_CACHE_READS` | unset | `1` = report only tokens billed near full rate |
| `BB_HOOK_DEBUG` | unset | `1` = append raw hook payloads to `$TMPDIR/bb-hook-input.jsonl` |

### `inject` vs `block`

`inject` (default) adds the cached answer as context and Claude still answers.
Safe, but the call still costs tokens — you save on quality and grounding, not
spend.

`block` stops the prompt and shows you the cached answer instead. **This is the
only mode that actually costs zero tokens**, and the only one where a wrong hit
is presented to you as though it were an answer. Only worth it with a strict
threshold (the default is cosine ≥ 0.95).

### Token counts and cost

Claude Code reports input tokens in three buckets that are **not** billed alike:
fresh input and cache *writes* cost roughly full rate, cache *reads* about a
tenth. A long turn can be 2 fresh tokens against 200,000 cache reads.

Brown Bear prices a model at one input rate, so the default (report the true
total) **overstates cost** for cache-heavy sessions. Two ways to fix it:

- `BB_EXCLUDE_CACHE_READS=1` — report only the near-full-rate tokens
- Add a pricing row for your `BB_MODEL`, or POST `cost_usd` yourself

Without a pricing row, `/ext/exchange` returns a warning rather than silently
recording $0.

## Verifying it works

```bash
# 1. Is the gateway reachable and ready?
curl -s -H "Authorization: Bearer $BB_EDGE_TOKEN" "$BB_GATEWAY_URL/ext/health"

# 2. Does the context hook produce hook JSON?
echo '{"prompt":"a question you have asked before"}' | python3 bb_context.py

# 3. Nothing happening? See exactly what Claude Code sends:
BB_HOOK_DEBUG=1 …            # then read $TMPDIR/bb-hook-input.jsonl
```

Silence from either hook is a valid outcome — no cache hit and nothing
retrievable means no output at all. That is why step 3 exists: the hooks are
deliberately quiet, so use the debug dump rather than guessing.

## The API, if you want to build your own client

All four require `Authorization: Bearer $BB_EDGE_TOKEN` (the liveness probe does
not).

```
GET  /api/health/live        → {"status":"ok"}                     (public)
GET  /ext/health             → readiness, threshold, top_k, collections

POST /ext/documents          → ingest into the knowledge corpus
     {text, source, project?, metadata?}
     ← {chunks_stored, ids[], source}

POST /ext/context            → cache check + retrieval, one call
     {prompt, project?, model?, k?, skip_cache?}
     ← hit:  {hit:true,  answer, score, matched_prompt, created_at, threshold}
       miss: {hit:false, reason, score, matched_prompt, near_miss, chunks[], threshold}

POST /ext/exchange           → store the pair + report usage
     {prompt, response, project?, model?, tokens_in?, tokens_out?,
      request_id?, cost_usd?, stale_after?, store?}
     ← {stored, cached_entry:{id,cacheable,stale_after}, token_event_id, warnings[]}
```

`score` and `matched_prompt` come back on every lookup, hit or miss, so a client
can apply its own stricter rule and a human can see *why* something matched.
Repeat a `request_id` and the usage is not counted twice.

## Sending files — `bb_file.py` (spec 007)

Extraction happens **on this machine**. Brown Bear stores the bytes and the text it
is handed; it runs no OCR, no PDF parser and no vision model, so what a file is
searchable by is decided entirely here.

```bash
python3 bb_file.py notes.md                       # text read directly
python3 bb_file.py scan.pdf --tags ops,retention  # pdftotext if present
python3 bb_file.py shot.png                       # tesseract if present
python3 bb_file.py chart.png --extract-cmd 'my-vision-tool {path}'
```

The content is hashed first and `GET /ext/files/{sha256}/exists` is checked, so a
file another machine already sent is never uploaded twice.

| Variable | Meaning |
|---|---|
| `BB_EXTRACT_CMD` | extraction command template; `{path}` is substituted |
| `BB_FILE_TIMEOUT` | seconds for extraction and upload (default 120) |

**A missing extractor is not an error.** The file uploads with no text, Brown Bear
marks it `stored` rather than `indexed`, and it stays downloadable and visible in
the graph while not being searchable. That is deliberate: a file you can find and
open beats a refused upload.

**Nothing is verified but the bytes.** The server re-hashes the upload and rejects a
digest mismatch, so file integrity is checked. Whether the *text* matches those
bytes cannot be checked without re-doing the extraction, so the extractor and this
machine's hostname are recorded and shown beside the text on `/files`. Treat
extracted text with the same scepticism as client-reported token counts.

## Reading files into the memory — `bb_media.py` (spec 009)

Spec 007 stores a file with the text a client extracted from it. On a machine with
no `pdftotext` and no `tesseract` that text is empty, so every PDF and screenshot
lands `stored` and unsearchable. **The one reader always present is Claude** — it
reads PDFs and images natively and translates as a matter of course — so this hook
splits ingestion in two and lets it do the reading.

```
Claude reads report-ja.pdf
  → hook stores the BYTES, returns the file_id and the command to send the text
  → Claude writes the English text (translating if needed), keeps the original
  → bb_media.py attach f_<id> --text-file en.txt --source-text-file ja.txt \
        --source-language ja --extractor "claude-opus-5" --file report-ja.pdf
  → indexed, retrievable in English, with the original stored beside it
```

Brown Bear still extracts nothing. There is no translator in the stack to use even
if we wanted one: `GET /ollama/api/tags` returns an embedding model and
`smollm2:135m`, which would produce a confident mistranslation — worse than none.

| Command | What it does |
|---|---|
| `bb_media.py hook` | the `PostToolUse` handler; reads the event on stdin |
| `bb_media.py store <path>` | send a file's bytes with no text |
| `bb_media.py attach <file_id> --text-file <p>` | send the reading; `-` reads stdin |

| Variable | Meaning |
|---|---|
| `BB_MEDIA_MAX_BYTES` | skip files larger than this (default 50 MB, the server's own cap) |
| `BB_MEDIA_TIMEOUT` | seconds for a request (default 60) |
| `BB_MEDIA_TYPES` | extra extensions to treat as media, comma separated |
| `BB_ENABLED` | `0` disables the hook without touching `settings.json` |

**Nothing is automatic, deliberately.** The hook stores the bytes and *asks*;
Claude decides whether the file is worth remembering. A screenshot of a terminal
should not become a corpus entry, and no rule in a hook can tell that from a
scanned contract.

**Which files trigger it.** An allowlist of extensions — `.pdf`, images, Office and
OpenDocument formats, `.epub`, `.rtf`. Source files and Markdown are ignored:
Claude reads those constantly, they are already in the repository, and uploading
them buries the documents that are only readable as pictures.

**The English text is what gets indexed.** The original language is stored beside
it under a labelled header, so a reader can check the translation against its
source — but it is not embedded, or one document would answer the same question
twice, in two languages, at two different scores.

**Against an older Brown Bear** — one without `POST /ext/files/{id}/extraction` —
`attach` falls back to re-sending the bytes with the text attached, which every
version since spec 007 accepts. Pass `--file` so it has something to re-send.

## Syncing configuration — `bb_sync.py` (spec 008)

Sends this machine's agent configuration to Brown Bear so `/agents` can show what
each machine is actually running, addressed as **machine → Global or project →
tool → file**.

```bash
python3 bb_sync.py                    # this checkout's .claude, under the repo name
python3 bb_sync.py --global           # ~/.claude, under the "Global" scope
python3 bb_sync.py --tool qwen --global
python3 bb_sync.py --zip              # one archive instead of a JSON body
python3 bb_sync.py --dry-run          # print what would be sent, send nothing
```

Nothing is automatic. A sync happens when you ask for one, which is why `/agents`
shows the age of every file's last sync rather than implying it is current.

**Run `--dry-run` the first time.** It prints exactly which files would leave the
machine, and a grouped count of what would not:

```
/Users/you/.claude → your-laptop/global/claude
  would send 7 file(s), 2 value(s) masked here
    + settings.json
    + settings.local.json
    + hooks/brownbear-context.py
    ...
    - 472 file(s) skipped: plugins/ is runtime state, not configuration
    - 125 file(s) skipped: file-history/ is runtime state, not configuration
    - 60 file(s) skipped: projects/ is runtime state, not configuration
```

### Getting it back — `--pull` (spec 010)

Brown Bear keeps the last 10 contents of every synced file, so a sync is a backup
rather than just a copy. Pulling is on demand and never automatic; nothing here
ever pushes configuration to a machine.

```bash
python3 bb_sync.py --global --pull            # print what it would write
python3 bb_sync.py --global --pull --apply    # actually write it
python3 bb_sync.py --global --pull --apply --force   # overwrite files that differ
```

Three refusals, each because the alternative is a file that looks right and is not:

| Refusal | Why |
|---|---|
| a file whose values were **masked** | writing `«redacted»` where an API key belongs produces a config that looks correct and fails at runtime. The server decides this and says so per file; the client only obeys. |
| a file that **differs locally** | restoring is for a machine that lost something, not for silently reverting work in progress. `--force` overrides. |
| **anything at all** without `--apply` | a restore that runs by accident is the one failure mode worse than no restore. |

A file deleted from the machine is kept and marked `removed`; it is not restored
unless you pass `--include-removed`, because restoring one resurrects something
somebody deleted.

The directory does not have to exist. `--pull --apply` on a machine that lost
`~/.claude` entirely recreates it, nested paths included.

### What is sent, and what is not

Selection is an **allowlist**, not a denylist, and that is load-bearing. A
`~/.claude` accumulates runtime state beside its settings — `projects/` is every
conversation transcript this machine has ever had, `plugins/repos/` is git clones,
`file-history/` is edit snapshots. On the machine this was written on that is 631
files, of which 7 are configuration. A denylist would need updating every time the
tool grows a new cache directory, and the failure mode is silent: megabytes of
transcripts uploaded as "settings".

| Sent | Not sent |
|---|---|
| `settings.json`, `settings.local.json`, `CLAUDE.md`, `.mcp.json`, `statusline-command.sh`, and the rest of the named set | anything else at the top level |
| everything under `agents/`, `commands/`, `skills/`, `hooks/`, `output-styles/`, `rules/` | `projects/`, `history/`, `file-history/`, `plugins/repos/`, `todos/`, `shell-snapshots/`, caches |
| `plugins/config.json` | `.credentials.json`, `.env*`, `*.pem`, `*.key` — never, at either end |

`--all` walks the whole directory instead. On a global `~/.claude` that includes
conversation transcripts; be deliberate.

### Secrets are masked twice, and only the second time counts

This script masks credential-shaped values before sending — an `env` block, a
`"...token": "..."` pair, an `sk-ant-…` literal, a PEM private key. The server masks
again before writing the row, and **that** pass is the guarantee: an older copy of
this script, or a hand-rolled `curl`, would skip the client half entirely. The count
in the output is the server's, and `/agents` shows it beside each file.

Files whose only content is a credential are refused at both ends rather than
masked — masking one leaves nothing to read.

| Variable | Meaning |
|---|---|
| `BB_MACHINE` | what this machine calls itself (default: hostname) |
| `BB_PROJECT` | project scope (default: the git repo name) |
| `BB_SYNC_TIMEOUT` | seconds for the upload (default 120) |

**`--no-prune` when you are pushing part of a directory.** By default a sync says
"this is the whole branch", and a file that is no longer here is marked `removed` —
kept and shown, never deleted. That is wrong for a partial push, so pass
`--no-prune` and nothing else in the branch is touched.

### Every request needs a User-Agent

Cloudflare rejects Python's default `Python-urllib/3.x` agent with `403` (error
1010, browser-integrity check). All five scripts set `brown-bear-client/1.0` for
that reason. Because the hooks **fail open and silent**, omitting it does not
produce an error — it produces a gateway that appears to work and never returns
anything. If you write your own client, set a User-Agent.
