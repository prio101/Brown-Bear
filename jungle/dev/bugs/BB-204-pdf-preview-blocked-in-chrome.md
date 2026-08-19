# Bug: A PDF never renders on `/files` — Chrome shows a subframe error instead

**Status:** Fixed — 2026-08-19, see *Resolution* at the end
**Severity:** High — the preview pane is half of what `/files` is for, and PDFs are the format the ingestion path was built around
**Points:** 2
**Branch:** `fix/bb-204-pdf-preview`
**Date:** 2026-08-19
**Regression in:** spec 007 §"Preview by file type" — designed this way, shipped with `007-file-ingestion`

---

## Symptom

Open `/files`, select a PDF. The preview pane stays empty: no document, no viewer
toolbar, just Chrome's compact error page — a grey panel with a broken-document
glyph — inside the frame.

```
GET /ext/files/f_<id>/preview   200 OK
Content-Type: application/pdf
                                 <-- the bytes arrive; the frame shows an error page

DevTools, request type "document", in a sub frame
```

Always, for every PDF, on every reload. Images preview normally. The download
link works. Nothing is logged on the server — this is a clean 200.

---

## Context

**Reads required:** this file only.

| Fact | Value |
|---|---|
| Component | `jungle/web/src/components/FileBrowser.tsx` (`Preview`), `jungle/app/brownbear/routers/files.py` (`preview`) |
| Environment | Chrome 151 on Windows; dashboard behind the edge at `127.0.0.1:8081` |
| Reachable via | `/files`, and the frame's own URL `/ext/files/{id}/preview` |
| Auth | `Authorization: Bearer <BB_EDGE_TOKEN>`, or Basic in a browser |
| First seen | 2026-08-18 |

What the route sent before the fix:

```
X-Content-Type-Options: nosniff
Content-Security-Policy: default-src 'none'; object-src 'none'; sandbox
Content-Disposition: inline
X-Frame-Options: SAMEORIGIN
```

and the frame that consumed it: `<iframe sandbox="" src="…/preview">`.

---

## Reproduction

Reproduced outside the stack, so that headers and frame attributes can be varied
one at a time: one origin serving a real PDF with the route's exact headers, and a
page framing it.

1. Serve any PDF with the pre-fix headers above, and frame it with
   `<iframe sandbox="" src="…">` from the same origin.
2. Load the framing page in Chrome and look at the frame:
   ```bash
   chrome --headless=new --virtual-time-budget=8000 \
          --window-size=900,700 --screenshot=out.png "http://127.0.0.1:8099/"
   ```
3. Sample a pixel inside the frame. Chrome's PDF viewer paints its background
   dark (`#282828`); its error page is light grey (`#dddddd`).

**Expected:** the viewer, i.e. a dark frame.
**Actual:** `(221, 221, 221)` — the error page.

Measured, varying one thing at a time (Chrome 151):

| Response CSP | `sandbox` attribute | Frame |
|---|---|---|
| `default-src 'none'; object-src 'none'; sandbox` | `""` | error page |
| `default-src 'none'; object-src 'none'; sandbox` | `allow-scripts` | error page |
| `default-src 'none'; object-src 'none'; sandbox` | `allow-scripts allow-same-origin` | error page |
| `default-src 'none'; object-src 'none'; sandbox` | `allow-scripts allow-same-origin allow-popups allow-forms allow-downloads allow-modals` | error page |
| `default-src 'none'; object-src 'none'; sandbox` | *absent* | **renders** |
| none at all | `""` | error page |

Headless Chrome mounts the viewer but does not paint the pages, so the screenshot
separates "viewer" from "error page" and not "viewer" from "blank viewer". That
the document itself renders was confirmed separately by navigating the main frame
to the PDF with `--print-to-pdf` and counting text-drawing operators in the
output — 58 text operators under the shipped policy.

---

## Root cause

**The `sandbox` attribute on the `<iframe>`.** A browser does not render a PDF the
way it renders an image; it navigates the frame to a viewer of its own, and that
viewer is a scripted document. A sandboxed frame is exactly what such a document
cannot load in, so Chrome abandons the navigation and paints the error page it
uses for a failed sub frame.

The symptom pointed the other way. A blocked frame reads as a framing-policy
problem, and this route had visibly been fussed over for framing policy — the edge
sets `X-Frame-Options: DENY` for the whole server and the route overrides it to
`SAMEORIGIN`, with a comment explaining why. Both `X-Frame-Options` headers turned
out to be correct and identical, and the response CSP — including the `sandbox`
directive that looks like the obvious suspect — does not block the viewer either:
with the attribute removed, a PDF served with the *original* strict policy renders,
text and all.

So the belief that was wrong was not about any header. It was the assumption
underneath the design: that `sandbox` is a free extra layer around a PDF because
"the browser's viewer sandboxes it anyway". The viewer is the thing being
sandboxed out of existence.

The isolation the attribute was reaching for is real, but it is not the frame's to
give. A PDF's JavaScript runs in the viewer's own engine — no DOM, no cookies, no
reach into the embedding page — whether or not the frame is sandboxed.

---

## Fix

- [x] `jungle/web/src/components/FileBrowser.tsx` — the PDF `<iframe>` carries no
      `sandbox` attribute, with the measurement recorded in a comment so it is not
      "hardened" back in.
- [x] `jungle/app/brownbear/routers/files.py` — PDFs get `PDF_HEADERS`:
      `default-src 'none'; object-src 'none'; frame-ancestors 'self'`. The `sandbox`
      directive is dropped (it is the same trap in header form, and other browsers'
      viewers are built the same way) and `frame-ancestors` added, which restricts
      framing in a form browsers do honour here. Images keep `INLINE_HEADERS`
      unchanged, `sandbox` included — an image needs no viewer.
- [x] `jungle/dev/features/007-file-ingestion.md` — the preview table, the "PDFs can
      carry JavaScript too" paragraph and the acceptance list now say this, since the
      spec is where the wrong belief was written down.

### Regression test

- [x] `jungle/app/tests/test_files.py::TestPreviewHeaders::test_a_pdf_is_not_sandboxed`
      — asserts the PDF response has no `sandbox` in its CSP while keeping
      `default-src 'none'`, `object-src 'none'`, `frame-ancestors`, `nosniff` and
      `SAMEORIGIN`. Fails on the unfixed code, which sent `sandbox`.
- [x] `…::TestPreviewHeaders::test_an_image_keeps_the_strict_policy` — the relaxation
      is for PDFs only.
- [x] `jungle/web/src/components/__tests__/FileBrowser.test.tsx` — "renders a PDF in
      an iframe with no sandbox attribute". The old test asserted `sandbox === ""`;
      it passed happily against a preview that never rendered, which is the other
      half of why this shipped.

---

## Acceptance Criteria

- [x] A PDF selected on `/files` shows the document in Chrome, not an error page
- [x] The regression tests fail on the unfixed code and pass on the fix
- [x] Images still preview, still under the strict policy with `sandbox`
- [x] The route still refuses to serve anything off the inline allowlist, still sends
      `nosniff`, and still cannot be framed by another origin
- [x] `.svg` still renders as source text, never inline

---

## Implementation Notes

- **A test can pass against a preview nobody can see.** Both the unit test and the
  spec's acceptance line described the *markup* ("in a sandboxed iframe") rather
  than the *outcome* ("a PDF is visible"). Anything whose failure mode is a clean
  200 plus a browser-side error page needs at least one check in a real browser.
- **Telling the two states apart headlessly:** screenshot to separate "viewer" from
  "error page"; `--print-to-pdf` plus a count of text-drawing operators to prove the
  document actually paints.
- **The nginx side was already right.** `location ~ ^/ext/files/[^/]+/preview$`
  re-declares `nosniff` and `Referrer-Policy` because `add_header` in a location
  replaces the inherited set. That trap was handled; this bug was elsewhere.
- **It came back once.** The first fix was lost when the working tree was reset, and
  the report arrived again unchanged. The regression tests above are what make the
  second loss loud instead of silent.

---

## Resolution

Fixed 2026-08-19. Verified end to end after `docker compose build app web`: the live
authenticated URL `http://127.0.0.1:8081/ext/files/{id}/preview` renders in Chrome
with its text intact, and the deployed bundle contains no `sandbox` attribute.
