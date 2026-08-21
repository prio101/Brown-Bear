// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FileBrowser } from "@/components/FileBrowser";
import type { FileRecord } from "@/lib/api/schemas";

/**
 * Preview selection by media type (spec 007 §7.6), and what each type may be
 * zoomed with (spec 011).
 *
 * The point of these is that the browser does the rendering and this component
 * only has to pick the right element. Getting that wrong is silent — a PDF in an
 * <img> shows a broken-image icon, and an SVG in an <img> would render script from
 * this origin — so each branch is asserted rather than eyeballed. The same applies
 * to the zoom: a lens offered over a PDF would track the pointer and magnify a
 * region the reader had scrolled away from.
 */

function file(overrides: Partial<FileRecord> = {}): FileRecord {
  return {
    file_id: "f_abc",
    sha256: "a".repeat(64),
    filename: "notes.md",
    media_type: "text/markdown",
    size_bytes: 165,
    project: "brownbear",
    source: "notes.md",
    extractor: "read directly",
    extracted_by: "laptop",
    has_preview: false,
    status: "indexed",
    error: null,
    chunk_count: 1,
    tags: [],
    created_at: "2026-08-17T09:00:00+00:00",
    indexed_at: "2026-08-17T09:00:00+00:00",
    extracted_chars: 165,
    inline_renderable: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => file({ extracted_text: "the extracted body" }),
    })),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** The lens maps the pointer onto the image's box, and this DOM measures every box
 *  as 0×0 — where the component correctly declines to place a lens at all. */
function measurePreviewsAs(width: number, height: number) {
  const rect = { left: 0, top: 0, right: width, bottom: height, width, height };
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
    ...rect,
    x: 0,
    y: 0,
    toJSON: () => rect,
  } as DOMRect);
}

describe("preview by media type", () => {
  it("renders a PDF in an iframe with no sandbox attribute", () => {
    // BB-204: the frame must NOT be sandboxed. Chrome refuses to run its built-in
    // PDF viewer in a sandboxed frame — under any token combination — and shows its
    // subframe error page instead, so asserting a sandbox here would lock in a
    // preview that never renders.
    render(<FileBrowser initial={[file({ media_type: "application/pdf", filename: "a.pdf", inline_renderable: true })]} />);

    const frame = document.querySelector("iframe");
    expect(frame).not.toBeNull();
    expect(frame!.hasAttribute("sandbox")).toBe(false);
    // ?original=1: the detail pane renders the blob itself (007 §7.6), and a PDF
    // whose client attached a PNG thumbnail must not frame the thumbnail.
    expect(frame!.getAttribute("src")).toBe("/ext/files/f_abc/preview?original=1");
  });

  it("renders an image in an img", () => {
    render(<FileBrowser initial={[file({ media_type: "image/png", filename: "a.png", inline_renderable: true })]} />);

    const image = document.querySelector("img");
    expect(image).not.toBeNull();
    // Full resolution, not the thumbnail: this one gets magnified (spec 011).
    expect(image!.getAttribute("src")).toBe("/ext/files/f_abc/preview?original=1");
    expect(document.querySelector("iframe")).toBeNull();
  });

  it("shows a placard for a type with no inline preview", () => {
    render(<FileBrowser initial={[file({ media_type: "text/markdown" })]} />);

    expect(document.querySelector("iframe")).toBeNull();
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText("text/markdown")).toBeTruthy();
  });

  it("never renders SVG as an image", () => {
    // It is an image format that is also a document format: inline from this
    // origin, its script would run with the reader's session. The server marks it
    // not inline-renderable and the component must honour that.
    render(
      <FileBrowser initial={[file({ media_type: "image/svg+xml", filename: "logo.svg", inline_renderable: false })]} />,
    );

    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("iframe")).toBeNull();
  });

  it("uses the thumbnail when one was supplied, whatever the type", () => {
    render(<FileBrowser initial={[file({ media_type: "application/zip", has_preview: true })]} />);
    expect(document.querySelector("img")).not.toBeNull();
  });
});

describe("the extraction pane", () => {
  it("does not call an indexed file empty before its text has loaded", async () => {
    // The list omits extracted_text, so the first paint has none. Saying "nothing
    // was extracted" there would report an indexed file as empty.
    render(<FileBrowser initial={[file({ extracted_chars: 165 })]} />);

    expect(screen.queryByText(/Nothing was extracted/)).toBeNull();
  });

  it("says so when a file genuinely has no extraction", async () => {
    // Two things this needs that the synchronous cases do not: the detail fetch
    // must also answer with no text, and the assertion must wait for it — the
    // pane shows "loading" until the request resolves.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => file({ extracted_chars: 0, status: "stored", extracted_text: null }),
      })),
    );
    render(<FileBrowser initial={[file({ extracted_chars: 0, status: "stored" })]} />);

    expect(await screen.findByText(/Nothing was extracted/)).toBeTruthy();
  });

  it("fetches the extraction for the selected file", () => {
    render(<FileBrowser initial={[file()]} />);
    expect(fetch).toHaveBeenCalledWith("/ext/files/f_abc", expect.objectContaining({ cache: "no-store" }));
  });
});

describe("status", () => {
  it("reports missing bytes rather than the stored status", () => {
    // A row whose blob has been pruned must not read as indexed.
    render(<FileBrowser initial={[file({ status: "indexed", blob_present: false })]} />);
    expect(screen.getByText(/Bytes missing/)).toBeTruthy();
  });

  it("shows the extractor, because it cannot be verified", () => {
    render(<FileBrowser initial={[file({ extractor: "tesseract 5.3" })]} />);
    const detail = screen.getByLabelText("File detail");
    expect(within(detail).getByText("tesseract 5.3")).toBeTruthy();
  });
});

describe("selection", () => {
  it("switches files when a row is clicked", () => {
    const files = [file(), file({ file_id: "f_def", filename: "second.md" })];
    render(<FileBrowser initial={files} />);

    fireEvent.click(screen.getByRole("button", { name: /second\.md/ }));

    expect(fetch).toHaveBeenCalledWith("/ext/files/f_def", expect.anything());
  });

  it("explains itself when there is nothing stored", () => {
    render(<FileBrowser initial={[]} />);
    expect(screen.getByText(/POST \/ext\/files/)).toBeTruthy();
  });
});


describe("zoom, per type (spec 011)", () => {
  beforeEach(() => measurePreviewsAs(400, 300));

  it("gives an image a lens under the pointer", () => {
    render(<FileBrowser initial={[file({ media_type: "image/png", filename: "a.png", inline_renderable: true })]} />);
    const image = screen.getByAltText("Preview of a.png");

    fireEvent.mouseMove(image.parentElement!, { clientX: 20, clientY: 20 });

    expect(screen.getByTestId("zoom-lens")).toBeTruthy();
    expect(screen.getByLabelText("Stronger lens")).toBeTruthy();
  });

  it("gives a PDF the viewer's own zoom and no lens", () => {
    render(<FileBrowser initial={[file({ media_type: "application/pdf", filename: "a.pdf", inline_renderable: true })]} />);

    expect(screen.getByText("fit")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Zoom in"));

    // The fragment drives the browser's viewer, and follows the query string.
    expect(document.querySelector("iframe")!.getAttribute("src")).toBe(
      "/ext/files/f_abc/preview?original=1#zoom=125",
    );
    expect(screen.queryByTestId("zoom-lens")).toBeNull();
  });

  it("steps the lens up and down without leaving the scale", () => {
    render(<FileBrowser initial={[file({ media_type: "image/png", filename: "a.png", inline_renderable: true })]} />);
    const image = screen.getByAltText("Preview of a.png");
    fireEvent.mouseMove(image.parentElement!, { clientX: 20, clientY: 20 });
    expect(screen.getByTestId("zoom-lens").textContent).toBe("2×");

    fireEvent.click(screen.getByLabelText("Stronger lens"));
    fireEvent.mouseMove(image.parentElement!, { clientX: 20, clientY: 20 });
    expect(screen.getByTestId("zoom-lens").textContent).toBe("3×");

    fireEvent.click(screen.getByLabelText("Weaker lens"));
    fireEvent.mouseMove(image.parentElement!, { clientX: 20, clientY: 20 });
    expect(screen.getByTestId("zoom-lens").textContent).toBe("2×");
  });

  it("says nothing to magnify when the bytes are gone", () => {
    // A pruned blob with no thumbnail has no pixels at all. A magnifier over a
    // broken image is worse than the placard that explains it.
    render(
      <FileBrowser
        initial={[file({ media_type: "image/png", inline_renderable: true, blob_present: false })]}
      />,
    );

    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText(/stored bytes are gone/)).toBeTruthy();
  });
});

describe("the gallery (spec 011)", () => {
  const images = [
    file({ file_id: "f_one", filename: "one.png", media_type: "image/png", inline_renderable: true }),
    file({ file_id: "f_two", filename: "two.jpg", media_type: "image/jpeg", inline_renderable: true }),
  ];

  it("opens on a click on the preview", () => {
    render(<FileBrowser initial={images} />);

    fireEvent.click(screen.getByRole("button", { name: "Open one.png in the gallery" }));

    expect(screen.getByRole("dialog").getAttribute("aria-label")).toBe("Image gallery: one.png");
  });

  it("holds every image in the list, so the arrows have somewhere to go", () => {
    render(<FileBrowser initial={images} />);
    fireEvent.click(screen.getByRole("button", { name: "Open one.png in the gallery" }));

    expect(screen.getByText("1 of 2")).toBeTruthy();
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(screen.getByText("2 of 2")).toBeTruthy();
  });

  it("leaves the detail pane on whichever image the reader stopped at", () => {
    // The extraction pane behind the overlay is the point of the page; coming out
    // of the gallery onto a different file's text would be a quiet mismatch.
    render(<FileBrowser initial={images} />);
    fireEvent.click(screen.getByRole("button", { name: "Open one.png in the gallery" }));
    fireEvent.keyDown(document, { key: "ArrowRight" });
    fireEvent.keyDown(document, { key: "Escape" });

    expect(fetch).toHaveBeenCalledWith("/ext/files/f_two", expect.anything());
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("excludes a PDF, and an SVG, from a gallery of images", () => {
    render(
      <FileBrowser
        initial={[
          file({ file_id: "f_pdf", filename: "a.pdf", media_type: "application/pdf", inline_renderable: true }),
          file({ file_id: "f_svg", filename: "logo.svg", media_type: "image/svg+xml", inline_renderable: false }),
        ]}
      />,
    );

    // Nothing to open: the PDF is not an image, and the SVG is not renderable here.
    expect(screen.queryByRole("button", { name: /in the gallery/ })).toBeNull();
  });

  it("magnifies a non-image's thumbnail but offers no gallery for it", () => {
    render(<FileBrowser initial={[file({ media_type: "application/zip", filename: "a.zip", has_preview: true })]} />);

    expect(document.querySelector("img")).not.toBeNull();
    expect(screen.queryByRole("button", { name: /in the gallery/ })).toBeNull();
  });
});
