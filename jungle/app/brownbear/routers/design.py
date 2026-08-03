"""Public design documentation (sprint 1, BB-109).

Besides ``/api/health/live`` this is the only route the edge publishes
unauthenticated, so it is deliberately inert:

  * it renders two Markdown files and touches nothing else — no database, no
    gateway, no ChromaDB, no Redis, no settings store. The page therefore still
    serves with every backing service stopped, and cannot be used to probe
    whether the stack is alive (``/api/health/live`` answers that on purpose).
  * rendering happens once and is cached. Markdown conversion per request would
    be unauthenticated CPU a stranger gets to spend.

The documents are mounted read-only from ``jungle/dev/design`` rather than baked
into the image, so editing one publishes it without a rebuild. A missing mount
degrades to 404 rather than breaking app startup.
"""

from __future__ import annotations

import html
from functools import lru_cache, partial
from pathlib import Path

import markdown
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response
from markdown.extensions.toc import TocExtension, slugify

from brownbear.config import get_settings

router = APIRouter(prefix="/design", tags=["design"])

# Public slug -> (filename on disk, display title). The keys are the whole
# allowlist: nothing else in the directory is reachable, so a stray file dropped
# into the mount is not published by accident.
DOCS: dict[str, tuple[str, str]] = {
    "design-book.md": ("DESIGN-BOOK.md", "Design Book"),
    "design-guide.md": ("DESIGN-GUIDE.md", "Design Guide"),
}

# Book first: it is the normative document. The guide is the reasoning behind it.
PAGE_ORDER = ("design-book.md", "design-guide.md")


def _doc_path(slug: str) -> Path:
    filename, _ = DOCS[slug]
    return Path(get_settings().design_dir) / filename


def _read_bytes(slug: str) -> bytes:
    path = _doc_path(slug)
    try:
        return path.read_bytes()
    except OSError as exc:  # missing mount, unreadable file
        raise HTTPException(
            status_code=404,
            detail=f"{DOCS[slug][1]} is not published on this instance.",
        ) from exc


def _prefixed_slug(prefix: str, value: str, separator: str) -> str:
    """Heading ids namespaced per document.

    Both documents are rendered into one page, and they share heading text
    ("Overview", "How to use"). Without a prefix the second document's anchors
    would silently point at the first one's headings.
    """
    return f"{prefix}-{slugify(value, separator)}"


def _render(slug: str) -> tuple[str, str]:
    """Return (body_html, toc_html) for one document."""
    text = _read_bytes(slug).decode("utf-8")
    anchor_prefix = slug.removesuffix(".md")
    md = markdown.Markdown(
        extensions=[
            "tables",
            "fenced_code",
            TocExtension(slugify=partial(_prefixed_slug, anchor_prefix), toc_depth="2-3"),
        ]
    )
    return _relink(md.convert(text)), md.toc


# The two documents cross-reference each other by filename, which is correct in
# the repo and dead on this page — "DESIGN-BOOK.md" would resolve to /DESIGN-BOOK.md
# and hit the edge's default deny. Both render into one page, so point them at
# the in-page sections instead.
_CROSS_LINKS = {
    'href="DESIGN-BOOK.md"': 'href="#design-book"',
    'href="DESIGN-GUIDE.md"': 'href="#design-guide"',
}


def _relink(body: str) -> str:
    for target, replacement in _CROSS_LINKS.items():
        body = body.replace(target, replacement)
    return body


@lru_cache(maxsize=1)
def _page() -> str:
    sections: list[str] = []
    tocs: list[str] = []
    for slug in PAGE_ORDER:
        body, toc = _render(slug)
        _, title = DOCS[slug]
        tocs.append(f'<p class="toc-title">{html.escape(title)}</p>{toc}')
        sections.append(
            f'<section id="{slug.removesuffix(".md")}" class="doc">{body}</section>'
        )
    return _SHELL.format(toc="\n".join(tocs), content="\n".join(sections))


@router.get("", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(_page())


@router.get("/{slug}")
def raw(slug: str) -> Response:
    """The raw Markdown, byte-for-byte — this is what LLM consumers read."""
    if slug not in DOCS:
        raise HTTPException(status_code=404, detail="No such document.")
    return Response(
        content=_read_bytes(slug),
        media_type="text/markdown; charset=utf-8",
    )


# --- presentation -----------------------------------------------------------
# Self-contained by requirement: no external stylesheet, font, script or image.
# Serving this from the Next.js frontend would mean publishing /_next/static/*
# unauthenticated — the whole application bundle exposed to serve one docs page.
#
# Styled from the Design Book's own tokens, so the page demonstrates the system
# it documents. Surfaces are the book's fixed chart surfaces (§2.2), which are
# deliberately not themed.
_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Brown Bear — Design Book</title>
<style>
:root {{
  color-scheme: light;
  --surface: #fcfcfb;
  --plane: #f9f9f7;
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --muted: #898781;
  --rule: #e1e0d9;
  --accent: #2a78d6;
  --font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --radius: 12px;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    color-scheme: dark;
    --surface: #1a1a19;
    --plane: #0d0d0d;
    --ink: #ffffff;
    --ink-2: #c3c2b7;
    --muted: #898781;
    --rule: #2c2c2a;
    --accent: #3987e5;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--plane);
  color: var(--ink);
  font: 400 16px/24px var(--font);
  letter-spacing: 0.5px;
}}
.wrap {{
  max-width: 1440px;
  margin: 0 auto;
  padding: 24px 16px 64px;
  display: grid;
  gap: 32px;
  grid-template-columns: 1fr;
}}
@media (min-width: 1024px) {{
  .wrap {{ grid-template-columns: 260px 1fr; padding-inline: 24px; }}
  nav {{ position: sticky; top: 24px; align-self: start; max-height: calc(100vh - 48px); overflow-y: auto; }}
}}
nav {{
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  padding: 16px;
  font-size: 14px;
  line-height: 20px;
}}
nav .toc-title {{
  margin: 8px 0;
  font: 500 14px/20px var(--font);
  letter-spacing: 0.1px;
  color: var(--muted);
  text-transform: uppercase;
}}
nav ul {{ list-style: none; margin: 0 0 16px; padding-left: 12px; }}
nav li {{ margin: 4px 0; }}
nav a {{ color: var(--ink-2); text-decoration: none; }}
nav a:hover {{ color: var(--accent); text-decoration: underline; }}
.doc {{
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  padding: 32px 24px;
  margin-bottom: 32px;
  overflow-wrap: break-word;
}}
.doc h1 {{ font: 400 32px/40px var(--font); letter-spacing: 0; margin: 0 0 16px; }}
.doc h2 {{
  font: 400 24px/32px var(--font);
  letter-spacing: 0;
  margin: 48px 0 12px;
  padding-top: 12px;
  border-top: 1px solid var(--rule);
}}
.doc h3 {{ font: 500 16px/24px var(--font); letter-spacing: 0.15px; margin: 24px 0 8px; }}
.doc p, .doc li {{ color: var(--ink-2); }}
.doc strong {{ color: var(--ink); }}
.doc a {{ color: var(--accent); }}
.doc code {{
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  background: var(--plane);
  border: 1px solid var(--rule);
  border-radius: 4px;
  padding: 1px 4px;
}}
.doc pre {{
  background: var(--plane);
  border: 1px solid var(--rule);
  border-radius: 8px;
  padding: 16px;
  overflow-x: auto;
}}
.doc pre code {{ background: none; border: 0; padding: 0; }}
.doc table {{
  display: block;
  width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
  font-size: 14px;
  margin: 16px 0;
}}
.doc th, .doc td {{
  border: 1px solid var(--rule);
  padding: 8px 12px;
  text-align: left;
  vertical-align: top;
}}
.doc th {{ font-weight: 500; color: var(--ink); }}
.doc blockquote {{
  margin: 16px 0;
  padding: 8px 16px;
  border-left: 3px solid var(--accent);
  color: var(--ink-2);
}}
.doc hr {{ border: 0; border-top: 1px solid var(--rule); margin: 32px 0; }}
header.masthead {{ grid-column: 1 / -1; }}
header.masthead h1 {{ font: 400 28px/36px var(--font); margin: 0 0 8px; }}
header.masthead p {{ color: var(--ink-2); margin: 0 0 12px; }}
.raw a {{
  display: inline-block;
  margin-right: 12px;
  font: 500 14px/20px var(--font);
  letter-spacing: 0.1px;
  color: var(--accent);
}}
a:focus-visible, nav a:focus-visible {{
  outline: 3px solid var(--accent);
  outline-offset: 2px;
  border-radius: 2px;
}}
</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <h1>Brown Bear — Design System</h1>
    <p>The normative Design Book and the Design Guide behind it. Public, read-only.</p>
    <p class="raw">
      <a href="/design/design-book.md">Design Book (raw Markdown)</a>
      <a href="/design/design-guide.md">Design Guide (raw Markdown)</a>
    </p>
  </header>
  <nav aria-label="Contents">{toc}</nav>
  <main>{content}</main>
</div>
</body>
</html>
"""
