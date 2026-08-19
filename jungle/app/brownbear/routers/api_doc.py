"""API documentation at /api-doc/v1 (spec 006).

Hand-rendered rather than FastAPI's `/docs`, which loads Swagger UI from
`cdn.jsdelivr.net`. This stack is built to run on a machine with no internet, so
`/docs` renders a blank page exactly when it is most needed.

The page documents the **edge contract**, not the app's route list. Those differ:
the schema advertises writes and a catch-all proxy the edge denies, and a client
written from the schema alone would call endpoints that return 403 through the
tunnel. See `brownbear/api_contract.py`.

Inert like `/design`: it renders two static structures and touches no database,
gateway or setting, so it serves while the stack is degraded.

Authenticated at the edge, unlike `/design` — design values describe nobody's
attack surface; an endpoint inventory does.
"""

from __future__ import annotations

import html
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from brownbear.api_contract import CONTRACT, REQUIREMENTS, Reach, by_group

router = APIRouter(prefix="/api-doc/v1", tags=["api-doc"])

#: The *contract's* version, not the app's. Bumped when a published endpoint
#: changes shape, which is a different event from a release.
CONTRACT_VERSION = "v1"

_REACH_LABEL: dict[Reach, str] = {
    Reach.PUBLIC: "Public",
    Reach.AUTHENTICATED: "Token required",
    Reach.DENIED: "Denied through the tunnel",
}

#: Status colours from DESIGN-BOOK.md §2.4. Paired with a text label, never used
#: alone — a reader must not have to distinguish these by hue.
_REACH_STYLE: dict[Reach, tuple[str, str]] = {
    Reach.PUBLIC: ("#0ca30c", "○"),
    Reach.AUTHENTICATED: ("#2a78d6", "●"),
    Reach.DENIED: ("#d03b3b", "✕"),
}


def annotated_schema(app_schema: dict[str, Any]) -> dict[str, Any]:
    """The OpenAPI document with reachability attached per operation.

    A machine consumer gets the same contract the page shows, rather than having to
    infer it — which is the mistake the page exists to prevent.
    """
    schema = dict(app_schema)
    schema["x-brownbear-contract-version"] = CONTRACT_VERSION
    # Headers that decide whether a request is answered at all. On the schema for
    # the same reason they are on the page: a client generated from the schema
    # alone would omit them and fail in a way that looks like nothing (BB-205).
    schema["x-brownbear-request-headers"] = [
        {
            "header": requirement.header,
            "applies_to": requirement.applies_to,
            "symptom": requirement.symptom,
            "why": requirement.why,
            "example": requirement.example,
        }
        for requirement in REQUIREMENTS
    ]
    schema["x-brownbear-contract"] = [
        {
            "method": endpoint.method,
            "path": endpoint.path,
            "reach": endpoint.reach.value,
            "group": endpoint.group,
            "summary": endpoint.summary,
        }
        for endpoint in CONTRACT
    ]

    paths = schema.get("paths") or {}
    annotated: dict[str, Any] = {}
    for path, operations in paths.items():
        annotated[path] = {}
        for method, operation in operations.items():
            declared = next(
                (
                    e
                    for e in CONTRACT
                    if e.path == path and e.method.lower() == method.lower()
                ),
                None,
            )
            enriched = dict(operation)
            # Absent rather than guessed: an unannotated operation is a signal that
            # the contract has not caught up, and the drift test fails on it.
            if declared is not None:
                enriched["x-brownbear-reach"] = declared.reach.value
            annotated[path][method] = enriched
    schema["paths"] = annotated
    return schema


def _rows(endpoints: list) -> str:
    cells = []
    for endpoint in endpoints:
        colour, glyph = _REACH_STYLE[endpoint.reach]
        denied = endpoint.reach is Reach.DENIED
        cells.append(
            "<tr>"
            f'<td><code>{html.escape(endpoint.method)}</code></td>'
            f'<td><code{" class=\"denied\"" if denied else ""}>{html.escape(endpoint.path)}</code></td>'
            f'<td><span class="reach" style="color:{colour}">'
            f'<span aria-hidden="true">{glyph}</span> {_REACH_LABEL[endpoint.reach]}</span></td>'
            f"<td>{html.escape(endpoint.summary)}</td>"
            "</tr>"
        )
    return "".join(cells)


@lru_cache(maxsize=1)
def _page() -> str:
    sections = []
    toc = []
    for group, endpoints in by_group().items():
        anchor = group.lower().replace(" ", "-")
        toc.append(f'<li><a href="#{anchor}">{html.escape(group)}</a></li>')
        sections.append(
            f'<section id="{anchor}">'
            f"<h2>{html.escape(group)}</h2>"
            '<div class="scroll"><table>'
            "<thead><tr><th>Method</th><th>Path</th><th>Through the tunnel</th>"
            "<th>What it does</th></tr></thead>"
            f"<tbody>{_rows(endpoints)}</tbody>"
            "</table></div></section>"
        )

    counts = {reach: sum(1 for e in CONTRACT if e.reach is reach) for reach in Reach}
    summary = (
        f"{counts[Reach.PUBLIC]} public · {counts[Reach.AUTHENTICATED]} token-required · "
        f"{counts[Reach.DENIED]} denied"
    )

    requirements = "".join(
        f"<p><strong>{html.escape(requirement.header)}</strong> — required on "
        f"{html.escape(requirement.applies_to)}. Without it: "
        f"<strong>{html.escape(requirement.symptom)}</strong>. "
        f"{html.escape(requirement.why)}</p>"
        f"<pre><code>{html.escape(requirement.example)}</code></pre>"
        for requirement in REQUIREMENTS
    )

    return _SHELL.format(
        version=CONTRACT_VERSION,
        summary=summary,
        requirements=requirements,
        toc="".join(toc),
        content="".join(sections),
    )


@router.get("", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(_page())


@router.get("/openapi.json")
def schema(request: Request) -> JSONResponse:
    return JSONResponse(annotated_schema(request.app.openapi()))


# --- presentation -----------------------------------------------------------
# Self-contained by requirement: no external stylesheet, script, font or image.
# Styled from the Design Book's tokens so the page matches the system it documents.
_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Brown Bear — API {version}</title>
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
  .wrap {{ grid-template-columns: 240px 1fr; padding-inline: 24px; }}
  nav {{ position: sticky; top: 24px; align-self: start; }}
}}
nav {{
  background: var(--surface); border: 1px solid var(--rule);
  border-radius: 12px; padding: 16px; font-size: 14px; line-height: 20px;
}}
nav ul {{ list-style: none; margin: 0; padding: 0; }}
nav li {{ margin: 4px 0; }}
nav a {{ color: var(--ink-2); text-decoration: none; }}
nav a:hover {{ color: var(--accent); text-decoration: underline; }}
header.masthead {{ grid-column: 1 / -1; }}
header.masthead h1 {{ font: 400 28px/36px var(--font); margin: 0 0 8px; }}
header.masthead p {{ color: var(--ink-2); margin: 0 0 8px; }}
.auth {{
  background: var(--surface); border: 1px solid var(--rule);
  border-left: 4px solid var(--accent); border-radius: 12px;
  padding: 16px; margin-top: 16px;
}}
section {{
  background: var(--surface); border: 1px solid var(--rule);
  border-radius: 12px; padding: 24px; margin-bottom: 24px;
}}
h2 {{ font: 400 24px/32px var(--font); margin: 0 0 12px; }}
.scroll {{ overflow-x: auto; max-width: 100%; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
th, td {{
  border-bottom: 1px solid var(--rule); padding: 8px 12px;
  text-align: left; vertical-align: top;
}}
th {{ font-weight: 500; color: var(--ink); white-space: nowrap; }}
td:nth-child(1), td:nth-child(2), td:nth-child(3) {{ white-space: nowrap; }}
code {{
  font-family: var(--mono); font-size: 13px; background: var(--plane);
  border: 1px solid var(--rule); border-radius: 4px; padding: 1px 4px;
}}
code.denied {{ text-decoration: line-through; color: var(--muted); }}
.reach {{ font-weight: 500; }}
pre {{
  background: var(--plane); border: 1px solid var(--rule);
  border-radius: 8px; padding: 16px; overflow-x: auto;
}}
pre code {{ background: none; border: 0; padding: 0; }}
a:focus-visible, nav a:focus-visible {{
  outline: 3px solid var(--accent); outline-offset: 2px; border-radius: 2px;
}}
</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <h1>Brown Bear — API {version}</h1>
    <p>
      What is reachable <strong>through the tunnel</strong>, which is not the same as
      what the application serves. The edge default-denies: anything not listed here
      answers <code>403</code> remotely even when it exists on the app.
    </p>
    <p>{summary}. Schema: <a href="/api-doc/v1/openapi.json">openapi.json</a>, annotated
      with the same reachability.</p>
    <p>This page says what you may call. The
      <a href="/api-doc/v1/handbook">Memory Handbook</a> says what happens when you
      do — the four layers, the order they are consulted in, and which of them can
      return an answer. Also as
      <a href="/api-doc/v1/handbook.md">Markdown</a> for a model on another machine.</p>
    <div class="auth">
      <p><strong>Authentication</strong> — one shared secret, two accepted forms.
      Machines send a bearer token; browsers cannot set a header from the address bar,
      so they sign in as user <code>bb</code> with the same secret as the password.</p>
<pre><code>curl -H "Authorization: Bearer $BB_EDGE_TOKEN" \\
  https://&lt;your-tunnel&gt;/ext/health</code></pre>
      <p>Unauthenticated requests to a token-required route return <code>401</code>
      with a <code>WWW-Authenticate</code> header. Requests to an unlisted path return
      <code>403</code>.</p>
    </div>
    <div class="auth">
      <p><strong>Required headers</strong> — these decide whether a request is
      answered at all. The first one is answered before the request reaches this
      stack, so a client that gets it wrong sees a failure with no trace on this
      side and, if it fails open, no trace on its own side either.</p>
      {requirements}
    </div>
  </header>
  <nav aria-label="Contents"><ul>{toc}</ul></nav>
  <main>{content}</main>
</div>
</body>
</html>
"""
