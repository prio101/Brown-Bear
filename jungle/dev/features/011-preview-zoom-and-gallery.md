# Feature: Preview zoom and the image gallery

**Status:** Done — 2026-08-21, see *Delivered* at the end. Browser verification still owed.
**Priority:** Medium — the `/files` detail pane can show a scan but not let anyone read it. A 420px-tall preview of an A4 page is legible to nobody, which makes "is this extraction wrong, or was the scan unreadable?" unanswerable from the dashboard.
**Points:** 3
**Branch:** `feat/011-preview-zoom-and-gallery`
**Date:** 2026-08-21
**Depends on:** spec 007 — the `/files` page, the `FileBrowser` component, and the `/ext/files/{id}/preview` route this extends.

---

## Overview

Two ways of looking closely at what was stored. A magnifying lens follows the
pointer over any previewed image and shows that region enlarged; clicking an image
opens it in a gallery over the page, with every other image in the list on a
filmstrip beneath it, arrow keys between them, and zoom and pan inside each one.

This is a viewing feature and nothing more. It adds no server-side rendering, no
imaging library, and no new bytes on disk: the lens is a second paint of the image
the browser has already decoded, and the gallery is the same blob at full size.

**What it deliberately does not do.** There is no hover lens over a PDF, and no
gallery of documents. Both boundaries are forced rather than chosen — see
*Decisions*. The extracted-text pane is untouched: it, not the picture, is still
the point of the page.

---

## Context

**Reads required:** this file only.

| Fact | Value |
|---|---|
| Page | `/files` — Next.js, `jungle/web/src/app/files/page.tsx` |
| Component changed | `jungle/web/src/components/FileBrowser.tsx` |
| Components added | `jungle/web/src/components/files/{Magnifier,PdfFrame,Lightbox}.tsx`, `previewSource.ts` |
| Stylesheet added | `jungle/web/src/styles/files.css`, imported from `global.css` |
| Route extended | `GET /ext/files/{file_id}/preview?original=1` → the file's own bytes rather than the client thumbnail |
| Route handler | `jungle/app/brownbear/routers/files.py` |
| Types renderable inline | `image/png`, `image/jpeg`, `image/webp`, `image/gif`, `application/pdf` — sniffed from the bytes, never taken from the client |
| Types in the gallery | the four image types above; **not** PDF, **not** `image/svg+xml` |
| Edge | `edge/nginx.conf.template:151` already proxies `^/ext/files/[^/]+/preview$` with `$is_args$args`, so a new query parameter needs no edge change |
| Design floor | `jungle/dev/design/DESIGN-GUIDE.md` Part 3 — no invented colour, size or spacing; focus visible on every control |

The one constraint that would otherwise have to be rediscovered: **`/preview`
serves the client-supplied thumbnail first**, and a thumbnail is capped at 2MB and
is typically 240px. Magnifying it magnifies its blur. Anything that zooms must ask
for `?original=1`.

---

## Decisions (locked)

| Decision | Choice | Consequence |
|---|---|---|
| Where the magnified pixels come from | **The same image element's URL, at `?original=1`** | One download serves both the preview and the lens. The detail pane now transfers full-size images, which is what 007 §7.6 said it should do ("the blob itself is what the detail pane renders") and what it was not doing |
| Zoom over a PDF | **The browser viewer's own zoom, via the `#zoom=` fragment** | Crisp at every step, and correct by construction. Costs a frame remount per zoom change, so the viewer returns to the top |
| Hover lens over a PDF | **Not offered** | The one deliberate gap in the request. A lens there would be wrong rather than absent — see below |
| What the gallery contains | **Image files only** | A `.docx`'s thumbnail is magnifiable in place but is not a gallery entry. SVG is excluded with everything else the server marks not-inline-renderable |
| Arrow keys in the gallery | **Always navigate, never pan** | Panning is the mouse drag. A key that means two things depending on zoom is hidden state |
| Lens above 1:1 | **Allowed, and labelled** | The badge reads `4× · past 1:1` once the lens is enlarging beyond the file's own pixels. Silently interpolating would let a reader conclude a scan is illegible when they have only run out of resolution |

### Why there is no lens over a PDF

A lens needs two things from the thing it magnifies: its pixels, and its scroll
position. A framed PDF gives neither. The browser renders it with a viewer that is
a separate document — in Chrome, a plugin document whose internals are not readable
from the page that frames it, same origin or not. So a lens over it would have to
guess, and it would guess wrong the moment the reader scrolled: the viewer would be
showing page 4 while the lens magnified the top of page 1, with nothing on screen
to say so. That is worse than no lens, and it is the failure mode this project's
design guide names first — a surface that looks like it is working.

The viewer's own zoom has neither problem. `#zoom=150` makes the viewer re-lay-out
at 150%, so text is re-rendered rather than scaled up, and the reader keeps the
viewer's own scrolling and page navigation.

### Why the gallery is images only

It was asked for as images only, and the boundary holds up: a gallery is a set of
things that are alike enough to flick between. A PDF is not — it has pages, and its
own viewer already navigates them. A `.docx` has no pixels at all; what it may have
is a thumbnail its client chose to send, which is a picture *of* the file rather
than the file. Those keep the lens, because magnifying a thumbnail in place is
still useful, and they say what they are: "the thumbnail its client supplied, not
an image file."

---

## Requirements

### The lens

- Follows the pointer over any previewed image, at a power the reader chooses from
  1.5×, 2×, 3×, 4×, 6× (default 2×)
- Shows the region actually under the pointer. The image is sized to its own pixels
  rather than letterboxed inside a wider box, because a lens mapped onto a box the
  image does not fill is offset from the cursor — subtly, and worse as the aspect
  ratios diverge
- Never shows blank space past the edge of the image: the window keeps tracking the
  pointer, the magnified content stops sliding
- States when it has passed the file's own resolution, and claims nothing when the
  image's natural size is not yet known
- Is not the only way to see detail — it is a pointer affordance, and the gallery is
  the keyboard and touch path to the same magnification

### The gallery

- Opens on a click on the preview; contains every image in the current list
- Full-resolution on the stage, thumbnails on the filmstrip. Twelve images must not
  cost twelve originals to draw twelve 72px tiles
- Keyboard: `←`/`→` move, `Home`/`End` jump, `+`/`−` zoom, `0` fits, `Esc` closes
- Click toggles fit ↔ 2×; drag pans a zoomed image, and the drag must not end by
  toggling the zoom it was panning
- Focus moves into the overlay, stays inside it while it is open, and returns to
  the element that opened it. The page behind does not scroll
- Wraps at both ends rather than disabling the arrows
- Selection follows the gallery: closing it leaves the detail pane — and the
  extraction — on the image the reader stopped at
- A zoom label never claims a percentage it cannot substantiate. Fit is `fit`, not
  `100%`, because fit is not the file's own scale

### The route

- `?original=1` prefers the file's own bytes; without it the thumbnail still comes
  first, because the list draws one per row
- It falls back to the thumbnail when the file's own type is not renderable inline,
  so asking for the original never 404s a preview that was working
- It widens nothing: the same byte-sniffed allowlist, the same headers, and SVG
  still never served inline

---

## Subtasks

### 11.1 — Full-resolution previews

- [x] `GET /ext/files/{id}/preview?original=1` in `routers/files.py` — reverses the
      thumbnail/original preference, with the allowlist check unchanged
- [x] Describe the parameter in `api_contract.py`, so `/api-doc/v1` carries it
- [x] `tests/test_files.py::TestPreviewOriginal` — the default, the reversal, the
      `.docx` fallback, and an SVG that must stay a 404

### 11.2 — The lens

- [x] `components/files/Magnifier.tsx` — pointer-tracked lens, clamped at the
      edges, power from a prop, `past 1:1` badge
- [x] `components/files/previewSource.ts` — `previewUrl()` and `isGalleryImage()`
- [x] `styles/files.css` — `.bb-zoom-*`, image sized to its own pixels, no
      transition on the lens
- [x] `__tests__/Magnifier.test.tsx` — offsets computed by hand and pinned

### 11.3 — PDF zoom

- [x] `components/files/PdfFrame.tsx` — `#zoom=` stepper over the unsandboxed frame
      (BB-204), keyed so the viewer reloads, with the note saying why there is no lens
- [x] Fragment ordering after the query string

### 11.4 — The gallery

- [x] `components/files/Lightbox.tsx` — stage, filmstrip, arrows, zoom, pan,
      keyboard, focus trap, scroll lock, focus restore
- [x] `__tests__/Lightbox.test.tsx`

### 11.5 — Wiring

- [x] `FileBrowser.tsx` — lens power state, gallery membership, selection follows
      the gallery, placard when the bytes are gone and no thumbnail remains
- [x] Extend `__tests__/FileBrowser.test.tsx` for zoom-per-type and the gallery

---

## Acceptance Criteria

- [x] A PNG preview magnifies under the pointer, and the magnified region is the one
      the pointer is on at every position including all four edges
- [x] The lens says `past 1:1` once it enlarges beyond the file's own pixels, and
      says nothing about 1:1 before the image's size is known
- [x] A PDF gets a zoom stepper and no lens; stepping it produces
      `…/preview?original=1#zoom=125`
- [x] Clicking an image opens a gallery holding every image in the list; a PDF and
      an SVG are not in it
- [x] `→` from the last image lands on the first; `Esc` closes; focus returns to the
      preview that opened it; the page behind does not scroll while it is open
- [x] Closing the gallery leaves the detail pane on the image last shown
- [x] A pruned blob with no thumbnail shows a placard saying the bytes are gone,
      not a broken image with a lens over it
- [x] `?original=1` on a `.docx` with a thumbnail returns the thumbnail, not a 404
- [x] `?original=1` on an SVG returns 404, and the inline headers are unchanged
- [x] Nothing in the new stylesheet or components invents a colour, a font size or
      an off-grid length (`npm run check:tokens` reports none from these files)
- [ ] **Owed: browser verification.** Every criterion above is asserted in the
      suite against happy-dom, which has no layout engine and no image decoder. What
      that cannot see: whether the lens *looks* aligned at a real layout, whether
      Chrome's viewer honours `#zoom=` at the version we ship against, and whether
      the scrim's `color-mix()` renders as intended in both themes. This is the same
      gap the roadmap already records for every Sprint 1 page

---

## Implementation Notes

- **`object-fit: contain` is the trap.** It was on the preview image, and it makes
  the element box wider than the pixels drawn inside it. A lens mapped onto the
  element then magnifies a region offset from the cursor — it looks like a working
  magnifier that is pointing slightly off. The magnified image is sized to itself
  (`width: auto`) so the element *is* the picture.
- **An iframe does not reload on a fragment change.** Setting `src` from
  `…/preview?original=1` to `…/preview?original=1#zoom=150` changes the attribute
  and nothing else, so the frame is keyed by the URL and React remounts it. The cost
  is that the viewer starts at the top again, which the note under it states.
- **Fragment after query.** `?original=1#zoom=150`, never `#zoom=150?original=1` —
  the latter makes the fragment part of nothing and the query never arrives.
- **A disabled button cannot take focus,** so it must not be in a focus trap's
  cycle: `focus()` on it silently does nothing and Tab appears to stop working. The
  gallery's zoom-out button is disabled every time it opens, which is exactly when
  the reader first presses Tab. The trap selects `button:not([disabled])`.
- **The click at the end of a drag.** `mouseup` after a pan is followed by a `click`
  on the same element, so a naive click-to-zoom handler ends every pan by zooming
  out. The drag records whether it moved more than 3px and the next click is
  swallowed.
- **`-0px` serialises as `0px`.** A lens clamped to the top-left corner computes
  `-0`; the DOM drops the sign, which is worth knowing before assuming an
  assertion has caught a sign error.
- **`image-rendering: pixelated` on the lens is deliberate.** Smoothing a magnified
  scan hides exactly the artefacts a reader is looking for.

---

## Open questions

- **A real lens over a PDF, with pdf.js.** Rendering pages to a canvas ourselves
  would put the pixels and the scroll position on this side of the boundary, and the
  same lens would work over a PDF. It costs a client-side dependency of roughly a
  megabyte and reverses 007's "no new rendering dependency" — and it moves PDF
  rendering bugs from the browser vendor to us. Recorded rather than taken: the
  native zoom answers the underlying need (read the small print) without it. What
  would change the answer is a reader wanting to compare two regions of one page,
  which zoom cannot do and a lens can.
- **Pinch-zoom in the gallery on touch.** The stage supports click-zoom and
  mouse-drag panning; a touch reader gets tap-to-zoom and no pan. Wiring pointer
  events would fix it, at the cost of the scroll-versus-pan ambiguity the lens
  deliberately avoids by staying a hover affordance.

---

## Delivered

**2026-08-21.** All of 11.1–11.5. One route parameter, four new frontend modules,
one stylesheet, and 32 new assertions across four suites (4 backend, 10 magnifier,
17 gallery, and the extended file-browser suite). `npm run build` compiles `/files`
through the deployment image; `pytest tests/test_files.py` is green at 38.

Two things found by writing the tests rather than the code: the focus trap's
disabled-button hole, and that the detail pane had been previewing thumbnails all
along where 007 §7.6 says it should render the blob.

Still owed: someone opening the page in a browser.
