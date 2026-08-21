# Feature: File ingestion with client-side extraction

**Status:** Open
**Priority:** High — retrieval is currently bounded by what someone remembers to paste as a string. Every design document, screenshot and PDF on a connected machine is invisible to the memory.
**Points:** 8
**Branch:** `feat/007-file-ingestion`
**Date:** 2026-08-17
**Depends on:** spec 005 — the `knowledge` collection, `gateway.ingest()`, and the chunk/embed path this reuses wholesale.

---

## Overview

Accept a file **together with the text already extracted from it on the client**,
store both, and put the text through the retrieval path that exists. The file
becomes a node in the memory graph, its chunks hang off it, and a reader can pull
up the original alongside what was extracted.

Extraction happens on the machine that has the file. Brown Bear does no OCR, no PDF
parsing and no image understanding — it is the shared memory, not the extractor.
That is the whole shape of this feature and it is why it costs 8 points instead of
13: no tesseract, no `pypdf`, no vision model, no rendering library, and no
background worker.

What it deliberately does **not** do: images are findable by the words the client
extracted from them, never by appearance. `nomic-embed-text` embeds text and
nothing else. It also never turns a file into an *answer* — files land in the RAG
layer, which serves supporting material; a cache hit must remain a prior answer
from `conversations`.

---

## Context

**Reads required:** this file only.

| Fact | Value |
|---|---|
| Ingest endpoint today | `POST /ext/documents` → `{text, source, project?, metadata?}` |
| Text cap today | `MAX_DOCUMENT_CHARS = 1_000_000` |
| Chunking | `chunk_chars=1200`, `chunk_overlap_chars=200` |
| Chunk identity | `content_id = c_<sha256(project\0chunk_text)[:32]>` |
| Retrieval collection | `knowledge` (role `retrieval`), cosine, 768-dim |
| Embedding model | `nomic-embed-text` — **text only**, 137M params, fast |
| Graph API | `GET /api/graph`, `GET /api/graph/node?id=<kind>:<value>` |
| Graph node kinds | `collection, project, model, source, exchange, chunk` |
| Edge rule | everything under `/ext/` is authenticated at the edge; new `/ext/files*` routes need **no nginx change** |
| Edge timeout on `/ext/` | 600s (`proxy_timeouts_long.conf`) |
| Auth | `Authorization: Bearer $BB_EDGE_TOKEN` |
| Client hooks | `clients/claude-code/bb_context.py`, `bb_exchange.py` — stdlib only, no `pip install` |
| Files to change | `jungle/app/brownbear/{blobs,files,gateway,graph,config}.py`, `routers/{ext,graph}.py`, `api_contract.py`, `compose.yaml`, `jungle/web/src/app/files/`, `clients/claude-code/` |

**No server-side extraction dependency is added by this spec.** That is a
requirement, not an accident: the client already opened the file, so it supplies
the text and — optionally — a preview image. Brown Bear stays a store.

---

## Flow

```
client machine                              Brown Bear
──────────────                              ──────────
1. sha256 the file locally
2. GET /ext/files/{sha256}/exists ─────────► already stored?
   ◄──────────────────────────────────────── {exists, indexed, chunk_count}
   exists → skip the upload entirely
   (a 40 MB PDF already sent from another machine is never sent twice)

3. extract text locally
   (pdftotext, OCR, vision model — the
    client's business, not ours)

4. POST /ext/files  multipart ─────────────► 5. verify sha256 of received bytes
     file       the original bytes             6. write blob, content-addressed
     extraction {text, extractor, pages?}      7. gateway.ingest(text) — unchanged
     preview    optional thumbnail (png)       8. link chunks → file_id
     meta       {project, source, tags?}       9. row: status=indexed
   ◄──────────────────────────────────────── {file_id, chunks_stored, deduplicated}

browse / retrieve
   GET /ext/context ──────────────────────► chunks carry file_id + media_type
   GET /ext/files/{id}            metadata + extracted text
   GET /ext/files/{id}?download=1 the original bytes
   GET /ext/files/{id}/preview    the client-supplied thumbnail
   /files (dashboard)             list, filter, preview, read extraction
   /graph                         file nodes, chunks, similarity
```

---

## Decisions (locked)

| Decision | Choice | Why |
|---|---|---|
| Memory level | **RAG (layer 4)**, with **Key Based (layer 3)** for identity | A file is supporting material, never a prior answer. Putting it in `conversations` would let a paragraph of a PDF be served as though Brown Bear had said it — the exact failure the two-collection split prevents. |
| Who extracts | **The client** | It has the file, the format-specific tooling and, on a laptop with a real GPU, the hardware. This host has a 2 GB MX450 that is not even wired to Ollama. |
| Blob storage | Content-addressed on a Docker volume, `blobs/<aa>/<bb>/<sha256>` | Dedup for free, immutable, streams without buffering. Postgres `bytea` bloats a database backed up as a unit; MinIO is a service for one feature. |
| Identity | `sha256` of the **bytes** | The same file from three machines is one blob and one embedding pass. Extends the Key Based layer's rule to binaries. |
| Preview | **Client-supplied**, optional | Rendering a PDF page server-side needs poppler; thumbnailing needs Pillow. The client already has the file open. This keeps the runtime image free of both. |
| Upload is synchronous | One request in, `200` with `chunks_stored` | Without extraction there is no slow step: `nomic-embed-text` is 137M params and chunks embed in milliseconds. A worker would be machinery for a problem that no longer exists. §Implementation notes records the threshold at which that stops being true. |
| Extraction is trusted | Recorded, attributed, never verified | Brown Bear cannot check that the text matches the bytes without doing the extraction itself. Same posture as `/ext/exchange`, where the client reports token counts and the contract says so plainly. |
| Image vectors | Out of scope | Text and image vectors cannot share a 768-dim space and still be compared to a 0.95 cutoff. Needs its own collection and its own spec. |

### Why extraction is stored, not just chunked

The chunks are what retrieval needs; the full extracted text is what a *person*
needs when they open a file and ask "what did this machine actually read out of
it?" Keeping only chunks makes a bad extraction invisible — you would see poor
retrieval and have no way to tell whether the file was scanned badly or the
embedding was at fault. The extracted text is stored whole, in Postgres, for that
question alone.

---

## Blockers

- **`python-multipart` is not installed.** FastAPI raises at import time on a
  `File(...)` parameter without it. Add to `pyproject.toml` first.
- **No blob volume exists.** `compose.yaml` needs a named volume at `/data/blobs`;
  the app runs as uid 10001 and the mount must be writable by it.
- **`X-Frame-Options: DENY` blocks PDF preview.** `edge/nginx.conf.template:61` sets
  it on every response, and `DENY` refuses framing *even same-origin* — so an
  `<iframe>` or `<embed>` PDF preview is blocked by the browser before it starts.
  The preview route needs its own `add_header X-Frame-Options SAMEORIGIN`.

  **nginx `add_header` replaces, it does not merge.** Declaring one header inside a
  `location` silently drops every `add_header` inherited from the `server` block, so
  that location must re-declare `X-Content-Type-Options` and `Referrer-Policy` too.
  Getting this wrong removes `nosniff` from precisely the route that serves
  attacker-supplied bytes.

All three are small.

---

## Requirements

### Trust and attribution

Extracted text arrives from a client and cannot be verified here. That is
acceptable — it is the same trust posture as token reporting — but it must be
*visible*:

- Every file records `extractor` (e.g. `pdftotext 24.02`, `tesseract 5.3`,
  `claude-opus-5 vision`) and `extracted_by` (the reporting machine's label).
- The dashboard and the graph show the extractor beside the text. A reader
  comparing a bad retrieval against its source needs to know what produced it.
- The bytes **are** verified: the server re-hashes what it received and rejects a
  mismatch against the client's claimed digest. Integrity of the file is checkable
  even though fidelity of the extraction is not.

### Security

A file upload is new attack surface on an internet-reachable endpoint.

- Size cap enforced **while streaming**: `BB_MAX_UPLOAD_BYTES`, default 50 MB. A cap
  checked after the read is not a cap.
- Media type from **content sniffing**, not the client's header and not the
  filename. Both are attacker-controlled.
- Blobs written **outside any served directory** under a generated name. The
  original filename is metadata, never a path — `../../etc/passwd` must be inert by
  construction.
- Serving sets `Content-Disposition: attachment` and `X-Content-Type-Options:
  nosniff`, and never returns `text/html` whatever was uploaded, so an uploaded page
  cannot execute on the dashboard's origin.
- Preview images are re-encoded or, failing that, served with the same
  attachment/nosniff headers. An "image" is an untrusted byte string.

### Failure behaviour

Degrade, never block — consistent with the rest of the gateway.

- Extraction text missing or empty → file is stored with `status=stored`, zero
  chunks, and is downloadable and visible in the graph. A file you can see but not
  search beats a lost upload.
- Embedding failure → blob kept, `status=failed` with the reason, retryable without
  re-uploading the bytes.
- Blob missing from the volume with a row present → `status=missing`, not a 500.
  Volumes get pruned.

---

## Subtasks

### 7.1 — Blob store

`brownbear/blobs.py`: content-addressed write/read/exists, streaming sha256, size
cap enforced mid-stream. Volume `bb_blobs` → `/data/blobs`. No FastAPI, no database
— a pure module with its own tests, like `gateway.chunk_text`.

### 7.2 — Database schema

Alembic migration adding `files`:

| Column | Type | Note |
|---|---|---|
| `id` | `text` PK | `f_<sha256[:32]>` — Key Based convention |
| `sha256` | `text` unique | full digest, verified server-side |
| `filename` | `text` | original name, display only |
| `media_type` | `text` | sniffed, not declared |
| `size_bytes` | `bigint` | |
| `project` | `text` | normalised scope, same rule as everywhere |
| `source` | `text` | retrieval label, joins to the existing `source` node |
| `extracted_text` | `text` | the full extraction, for human inspection |
| `extractor` | `text` | what produced it |
| `extracted_by` | `text` | which machine reported it |
| `has_preview` | `bool` | |
| `status` | `enum` | `indexed, stored, failed, missing` |
| `error` | `text` null | |
| `chunk_count` | `int` | |
| `created_at` / `indexed_at` | `timestamptz` | |

### 7.3 — API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/ext/files/{sha256}/exists` | dedup precheck — skip uploading what is already here |
| `POST` | `/ext/files` | multipart: `file`, `extraction`, optional `preview`, `meta` |
| `GET` | `/ext/files` | list, filtered by project / status / media type |
| `GET` | `/ext/files/{id}` | metadata **and the extracted text** |
| `GET` | `/ext/files/{id}?download=1` | the original bytes |
| `GET` | `/ext/files/{id}/preview` | the client-supplied thumbnail |
| `DELETE` | `/ext/files/{id}` | remove blob, row and chunks together |

All under `/ext/`, so the edge publishes them with no nginx change. Declare each in
`api_contract.py` or `scripts/check_edge_contract.py` fails the build.

`DELETE` is deliberate: without it the corpus is append-only and a wrongly-ingested
file is permanent. It must remove the chunks too, or retrieval keeps serving text
whose file is gone.

### 7.4 — Ingest path

`brownbear/files.py`: verify digest → store blob → persist row → `gateway.ingest()`
→ stamp `file_id` and `media_type` into each chunk's metadata → update row. One
transaction boundary per stage, so a failure part-way leaves a coherent record
rather than a blob with no row.

### 7.5 — Organisation

What makes this a corpus rather than a folder. All derived, none hand-maintained:

- **Cross-machine dedup** by content hash — the same PDF from three laptops is one
  entry with three reporting machines recorded.
- **Project scoping** on the existing normalised key, so a file is scoped exactly
  as exchanges and chunks already are.
- **Near-duplicate detection**: on ingest, query `knowledge` with the first chunk's
  vector; a score above ~0.97 against a *different* file is surfaced as a possible
  duplicate. Two exports of the same document under different filenames hash
  differently and would otherwise both sit there.
- **Orphan and staleness flags**: files with zero chunks, files whose blob is
  missing, files never returned by any retrieval — all queryable, all shown.
- **Tags** from the `meta` part, free-form, filterable.

### 7.6 — Browsing: `/files` dashboard page

- List: filename, project, media type, size, extractor, chunk count, status, age.
  Filter by project and status; sort by size and date.
- Detail: **preview pane**, **extracted-text pane** showing exactly what was
  indexed, and the **chunk list** with each chunk's text and id.
- The extracted-text pane is the point of the page. It answers "what did the memory
  actually read out of this file", which is unanswerable today.

#### Preview by file type

The browser already renders the two formats that matter, so this needs no server-
side rendering dependency at all:

| Type | Detail preview | Server work | New dependency |
|---|---|---|---|
| `text/plain`, `text/markdown`, JSON, CSV | The extracted text is the content — render it | none | none |
| `image/png`, `image/jpeg`, `image/webp`, `image/gif` | `<img>` — native | serve inline with the **sniffed** type | none |
| `application/pdf` | `<iframe>`, **not** sandboxed — see BB-204 | serve inline, relax `X-Frame-Options` on this route only, and leave `sandbox` out of its CSP | none |
| `image/svg+xml` | **Rendered as text, never as an image** | — | none |
| docx, xlsx, zip, anything else | Media-type placard + extracted text + download | none | none |

**Thumbnails still earn their place, but for the list, not the detail view.** Native
rendering handles detail; a list of forty rows must not ship forty PDFs to draw
forty 240px tiles. So the client-supplied preview is what the list shows, and the
blob itself is what the detail pane renders.

**SVG is excluded from inline rendering deliberately.** It is an image format that
is also a document format: an `.svg` can carry `<script>`, and served inline from
this origin that script runs with the reader's session. It is previewed as source
text, like any other text file.

**PDFs can carry JavaScript too, and the sandbox that was meant to contain it does
not work here (BB-204).** A browser renders a PDF with a built-in viewer that is
itself a scripted document, and a sandbox is what that viewer cannot survive: Chrome
answers a sandboxed PDF frame with its subframe error page instead of the document,
under every combination of sandbox tokens. So the frame carries no `sandbox`
attribute and the PDF response carries no `sandbox` directive; it gets
`Content-Security-Policy: default-src 'none'; object-src 'none'; frame-ancestors 'self'`
instead. Images — which need no viewer — keep the strict policy including `sandbox`.

What contains a hostile PDF is the browser's own architecture: its JavaScript runs
in the viewer's engine, with no DOM, no cookies and no reach into the page framing
it. What this route still guarantees is that it never hands back something *other*
than a PDF or an image — `nosniff`, plus a media type sniffed from the bytes against
a five-type allowlist.

Everything not on the inline allowlist keeps `Content-Disposition: attachment`.

**Extended by spec 011 (2026-08-21).** Rendering the preview is not the same as being
able to read it: a 420px-tall preview of an A4 scan is legible to nobody. 011 adds a
magnifying lens over images and the browser viewer's own zoom over PDFs, plus a
gallery over image files. It also closes a gap between this section and the code —
"the blob itself is what the detail pane renders" was the intent, but the pane called
`/preview`, which prefers the client's thumbnail; it now asks for `?original=1`.

### 7.7 — Graph integration

- `graph.py`: node kind `file`, edges `chunk --derived_from--> file` and
  `file --belongs_to--> project`.
- `MemoryGraph.tsx`: a shape and colour for `file` in `KIND_STYLE`; the detail panel
  shows the preview thumbnail, the extractor, and a link to `/files/{id}`.
- `status` must be visible on the node. An unsearchable file that looks identical to
  a searchable one is the worst outcome here.

### 7.8 — Client hook

`clients/claude-code/bb_file.py`, stdlib only, matching the existing hooks:
hash → `exists` precheck → extract with whatever the machine has → POST. Extraction
is pluggable via `BB_EXTRACT_CMD` so a machine with `pdftotext`, one with
`tesseract`, and one with a local vision model all work without changing the hook.
Document it in `clients/claude-code/README.md` alongside the other two.

---

## Acceptance Criteria

- [ ] A Markdown file plus its text uploaded through the tunnel is retrievable by
      that content through `POST /ext/context` in the same request cycle.
- [ ] A PDF's client-extracted text is chunked, and each chunk records `file_id`.
- [ ] A PNG plus client-run OCR text is retrievable by the OCR'd words.
- [ ] `GET /ext/files/{sha256}/exists` returns true for an already-stored file, and
      a second upload returns `deduplicated: true` without re-embedding.
- [ ] A digest mismatch between claimed and received bytes is rejected with `422`.
- [ ] A 60 MB upload is refused mid-stream, not after buffering.
- [ ] A file uploaded with empty extraction is stored, downloadable, visible in the
      graph, and reports `status=stored` with zero chunks.
- [ ] A file whose blob was deleted from the volume reports `status=missing`.
- [ ] An uploaded `.html` file is never served as `text/html`.
- [ ] An uploaded `.svg` renders as source text, never as an image.
- [ ] A PNG and a PDF both preview inline in the browser; a `.docx` falls back to the
      extracted-text pane and a download link. Checked in Chrome, not only in a test:
      the PDF failure mode (BB-204) is a clean 200 with an error page in the frame.
- [ ] The PDF preview frame has **no** `sandbox` attribute and the PDF response has
      **no** `sandbox` CSP directive — either one blocks the browser's viewer.
- [ ] The preview route returns `X-Frame-Options: SAMEORIGIN` **and still returns**
      `X-Content-Type-Options: nosniff` and `Referrer-Policy` — proving the nginx
      `add_header` replacement trap was handled.
- [ ] `DELETE /ext/files/{id}` removes the chunks; retrieval stops returning them.
- [ ] `/files` shows the preview, the full extracted text, and the chunk list.
- [ ] The graph shows a `file` node with its chunks and its extractor.
- [ ] `scripts/check_edge_contract.py` passes with the new endpoints declared.
- [ ] `/api-doc/v1/handbook.md` states that extraction happens on the client and is
      recorded but not verified.

---

## Implementation Notes

**Order.** 7.1 and 7.2 first — everything needs identity and somewhere to put
bytes. 7.3 and 7.4 together. 7.6 and 7.7 last: neither can show a node kind with no
rows behind it. 7.8 can land any time after 7.3.

**Do not re-embed on re-upload.** Chunk ids are `sha256(project + chunk_text)`, so
identical text re-ingested is an upsert. With blob-level dedup and the `exists`
precheck, the same PDF from three machines costs one upload, one extraction and one
embedding pass.

**When synchronous stops being right.** A 1M-character extraction is ~830 chunks,
batched 32 at a time — roughly 26 embed calls. Measure it: if that exceeds ~30s on
this host, split the ingest into `202 Accepted` plus an APScheduler worker claiming
`pending` rows. The scheduler is already running for aggregation. Do not build that
until the number says so.

**Retention is unowned.** Blobs are the first thing in this stack to consume real
disk (946 GB free today, and nothing removes them). Either spec 004 grows a blob
sweep or this ships one. Left unowned, the volume grows until the host fills.

---

## Open questions

1. **Auto-ingest.** Should the Claude Code hooks ingest files a session reads
   automatically, or is ingestion always deliberate? Auto fills the corpus fast and
   fills it with noise just as fast. Leaning deliberate, with an explicit command.
2. **Re-extraction.** When a machine gets a better extractor, how does an existing
   file get re-extracted? The blob is here, so the bytes need not move — but
   nothing currently asks a client to redo work. A `needs_reextraction` flag the
   client polls?
3. **Visual similarity.** Findability by appearance needs a CLIP-class model and a
   separate collection, since image and text vectors cannot share a space. Its own
   spec — 008?
4. **Size cap.** 50 MB is a guess. The real constraint is embedding time for the
   extracted text, not the byte count of the original.
