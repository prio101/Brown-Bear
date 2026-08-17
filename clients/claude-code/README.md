# Claude Code ↔ Brown Bear context gateway

Two hooks that put Brown Bear in front of Claude on any machine:

| Hook | Event | What it does |
|---|---|---|
| `bb_context.py` | `UserPromptSubmit` | Before each prompt: POSTs it to `/ext/context`, injects a cached answer or retrieved chunks |
| `bb_exchange.py` | `Stop` | After each turn: POSTs prompt + answer + token usage to `/ext/exchange` |

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

### Every request needs a User-Agent

Cloudflare rejects Python's default `Python-urllib/3.x` agent with `403` (error
1010, browser-integrity check). All three hooks set `brown-bear-client/1.0` for
that reason. Because the hooks **fail open and silent**, omitting it does not
produce an error — it produces a gateway that appears to work and never returns
anything. If you write your own client, set a User-Agent.
