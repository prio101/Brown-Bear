"""The memory handbook at /api-doc/v1/handbook (spec 006).

Served under the API doc's prefix because it answers the question the endpoint
inventory raises and cannot itself answer: `/ext/context` returns an answer or
some chunks, and nothing in that response says which store produced it or what it
guarantees. A client written from the endpoint list alone will trust a miss too
little and a hit too much.

Three representations of one source (`brownbear/handbook.py`):

    /api-doc/v1/handbook        HTML, for a person
    /api-doc/v1/handbook.md     Markdown, for a model on another machine
    /api-doc/v1/handbook.json   JSON, for a program

The Markdown route is the point of the exercise. A remote LLM reading the styled
page would spend its context window on the stylesheet, which is the same reason
`/design/{slug}` serves raw Markdown alongside the rendered book.

A separate router rather than more routes on `api_doc.py`: that module is pinned
by `tests/test_api_doc.py::TestInertness` to a single import, which is what keeps
the endpoint inventory renderable while the stack is down. This module honours the
same constraint — it imports pure data and a Markdown renderer, and touches no
database, connector or settings store, so it also serves while degraded.

Authenticated at the edge, like the rest of `/api-doc/`. The handbook describes
scoping rules, thresholds and stored-data semantics; that is a description of the
attack surface in a way that design tokens are not.
"""

from __future__ import annotations

from functools import lru_cache

import markdown
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse, Response
from markdown.extensions.toc import TocExtension

from brownbear.handbook import HANDBOOK_VERSION, to_json, to_markdown

router = APIRouter(prefix="/api-doc/v1", tags=["api-doc"])


@lru_cache(maxsize=1)
def _rendered() -> tuple[str, str]:
    """(body_html, toc_html), converted once.

    Markdown conversion per request would be CPU spent re-deriving a document that
    cannot change without a restart — the source is a Python literal.
    """
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", TocExtension(toc_depth="2-3")]
    )
    return md.convert(to_markdown()), md.toc


@lru_cache(maxsize=1)
def _page() -> str:
    body, toc = _rendered()
    return _SHELL.format(version=HANDBOOK_VERSION, toc=toc, content=body)


@router.get("/handbook", response_class=HTMLResponse)
def handbook_page() -> HTMLResponse:
    return HTMLResponse(_page())


@router.get("/handbook.md")
def handbook_markdown() -> Response:
    """The handbook as Markdown — what an LLM on another machine reads."""
    return Response(content=to_markdown(), media_type="text/markdown; charset=utf-8")


@router.get("/handbook.json")
def handbook_json() -> JSONResponse:
    """The same document structured, for a program that wants the fields."""
    return JSONResponse(to_json())


# --- presentation -----------------------------------------------------------
# Self-contained by requirement, and styled from the Design Book's tokens so the
# page matches /api-doc/v1 beside it. No external stylesheet, script, font or image.
_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Brown Bear — Memory Handbook {version}</title>
<style>
:root {{
  color-scheme: light;
  --surface: #fcfcfb; --plane: #f9f9f7; --ink: #0b0b0b; --ink-2: #52514e;
  --muted: #898781; --rule: #e1e0d9; --accent: #2a78d6;
  --font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --mono: ui-monospace, SFMono-Regular, Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    color-scheme: dark;
    --surface: #1a1a19; --plane: #0d0d0d; --ink: #ffffff; --ink-2: #c3c2b7;
    --muted: #898781; --rule: #2c2c2a; --accent: #3987e5;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--plane); color: var(--ink);
  font: 400 16px/24px var(--font); letter-spacing: 0.5px;
}}
.wrap {{
  max-width: 1440px; margin: 0 auto; padding: 24px 16px 64px;
  display: grid; gap: 32px; grid-template-columns: 1fr;
}}
@media (min-width: 1024px) {{
  .wrap {{ grid-template-columns: 260px 1fr; padding-inline: 24px; }}
  nav {{ position: sticky; top: 24px; align-self: start;
        max-height: calc(100vh - 48px); overflow-y: auto; }}
}}
nav {{
  background: var(--surface); border: 1px solid var(--rule);
  border-radius: 12px; padding: 16px; font-size: 14px; line-height: 20px;
}}
nav ul {{ list-style: none; margin: 0; padding-left: 12px; }}
nav li {{ margin: 4px 0; }}
nav a {{ color: var(--ink-2); text-decoration: none; }}
nav a:hover {{ color: var(--accent); text-decoration: underline; }}
header.masthead {{ grid-column: 1 / -1; }}
header.masthead h1 {{ font: 400 28px/36px var(--font); margin: 0 0 8px; }}
header.masthead p {{ color: var(--ink-2); margin: 0 0 12px; }}
.raw a {{
  display: inline-block; margin-right: 12px;
  font: 500 14px/20px var(--font); color: var(--accent);
}}
.doc {{
  background: var(--surface); border: 1px solid var(--rule);
  border-radius: 12px; padding: 32px 24px; overflow-wrap: break-word;
}}
.doc h1 {{ font: 400 32px/40px var(--font); letter-spacing: 0; margin: 0 0 16px; }}
.doc h2 {{
  font: 400 24px/32px var(--font); letter-spacing: 0; margin: 48px 0 12px;
  padding-top: 12px; border-top: 1px solid var(--rule);
}}
.doc h3 {{ font: 500 16px/24px var(--font); margin: 32px 0 8px; }}
.doc p, .doc li {{ color: var(--ink-2); }}
.doc strong {{ color: var(--ink); }}
.doc a {{ color: var(--accent); }}
.doc blockquote {{
  margin: 12px 0; padding: 8px 16px;
  border-left: 3px solid var(--accent); color: var(--ink-2);
}}
.doc code {{
  font-family: var(--mono); font-size: 13px; background: var(--plane);
  border: 1px solid var(--rule); border-radius: 4px; padding: 1px 4px;
}}
.doc pre {{
  background: var(--plane); border: 1px solid var(--rule);
  border-radius: 8px; padding: 16px; overflow-x: auto;
}}
.doc pre code {{ background: none; border: 0; padding: 0; }}
.doc table {{
  display: block; width: 100%; overflow-x: auto;
  border-collapse: collapse; font-size: 14px; margin: 16px 0;
}}
.doc th, .doc td {{
  border: 1px solid var(--rule); padding: 8px 12px;
  text-align: left; vertical-align: top;
}}
.doc th {{ font-weight: 500; color: var(--ink); white-space: nowrap; }}
a:focus-visible, nav a:focus-visible {{
  outline: 3px solid var(--accent); outline-offset: 2px; border-radius: 2px;
}}
</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <h1>Brown Bear — Memory Handbook</h1>
    <p>What this stack remembers, in what order it is consulted, and what each
      layer will and will not return. Companion to
      <a href="/api-doc/v1">the endpoint contract</a>.</p>
    <p class="raw">
      <a href="/api-doc/v1/handbook.md">Markdown (for an LLM)</a>
      <a href="/api-doc/v1/handbook.json">JSON (for a program)</a>
      <a href="/ext/health">Live values</a>
    </p>
  </header>
  <nav aria-label="Contents">{toc}</nav>
  <main class="doc">{content}</main>
</div>
</body>
</html>
"""
