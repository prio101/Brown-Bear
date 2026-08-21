// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Lightbox } from "@/components/files/Lightbox";

/**
 * The gallery (spec 011 §11.4).
 *
 * What is pinned here is the part a reader notices only when it is wrong: that the
 * stage asks for the original and the filmstrip does not, that the keyboard can
 * both drive and leave the overlay, and that focus comes back to where it started.
 * A lightbox that traps focus and never returns it is a page a keyboard reader is
 * stuck on.
 */

const ITEMS = [
  { fileId: "f_one", filename: "one.png" },
  { fileId: "f_two", filename: "two.jpg" },
  { fileId: "f_three", filename: "three.webp" },
];

function open(overrides: Partial<Parameters<typeof Lightbox>[0]> = {}) {
  const props = {
    items: ITEMS,
    index: 0,
    onIndexChange: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
  const view = render(<Lightbox {...props} />);
  return { ...props, view };
}

afterEach(cleanup);

describe("what it asks the server for", () => {
  it("shows the original on the stage and thumbnails in the filmstrip", () => {
    open();

    // The stage is what gets zoomed, so it needs the file's own pixels.
    expect(screen.getByTestId("lightbox-image").getAttribute("src")).toBe(
      "/ext/files/f_one/preview?original=1",
    );
    // The strip draws 72px tiles and must not download three originals to do it.
    expect(screen.getByAltText("two.jpg").getAttribute("src")).toBe("/ext/files/f_two/preview");
  });

  it("renders nothing at all for an empty gallery", () => {
    const { view } = open({ items: [], index: 0 });
    expect(view.container.firstChild).toBeNull();
  });
});

describe("the keyboard", () => {
  it("moves between images with the arrows", () => {
    const { onIndexChange } = open({ index: 1 });

    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(onIndexChange).toHaveBeenCalledWith(2);

    fireEvent.keyDown(document, { key: "ArrowLeft" });
    expect(onIndexChange).toHaveBeenCalledWith(0);
  });

  it("wraps rather than stopping at the ends", () => {
    // A gallery that stops has to explain why it stopped, and there is nothing to
    // explain: the reader wanted the next picture.
    const { onIndexChange } = open({ index: 2 });

    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(onIndexChange).toHaveBeenCalledWith(0);
  });

  it("jumps to the ends with Home and End", () => {
    const { onIndexChange } = open({ index: 1 });

    fireEvent.keyDown(document, { key: "Home" });
    expect(onIndexChange).toHaveBeenCalledWith(0);

    fireEvent.keyDown(document, { key: "End" });
    expect(onIndexChange).toHaveBeenCalledWith(2);
  });

  it("closes on Escape", () => {
    const { onClose } = open();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("zooms with + and − and fits with 0", () => {
    open();
    const stage = screen.getByTestId("lightbox-image");
    expect(stage.style.transform).toContain("scale(1)");

    fireEvent.keyDown(document, { key: "+" });
    expect(stage.style.transform).toContain("scale(1.5)");

    fireEvent.keyDown(document, { key: "+" });
    expect(stage.style.transform).toContain("scale(2)");

    fireEvent.keyDown(document, { key: "-" });
    expect(stage.style.transform).toContain("scale(1.5)");

    fireEvent.keyDown(document, { key: "0" });
    expect(stage.style.transform).toContain("scale(1)");
  });
});

describe("zoom and pan with the mouse", () => {
  it("toggles between fit and 2× on click", () => {
    open();
    const stage = screen.getByTestId("lightbox-image");

    fireEvent.click(stage);
    expect(stage.style.transform).toContain("scale(2)");

    fireEvent.click(stage);
    expect(stage.style.transform).toContain("scale(1)");
  });

  it("pans a zoomed image and does not toggle the zoom off at the end of the drag", () => {
    // The mouseup that finishes a pan is followed by a click on the same element.
    // Without suppression, every pan ends by zooming back out.
    open();
    const stage = screen.getByTestId("lightbox-image");
    fireEvent.click(stage);

    fireEvent.mouseDown(stage, { clientX: 100, clientY: 100 });
    fireEvent.mouseMove(window, { clientX: 140, clientY: 130 });
    fireEvent.mouseUp(window);
    fireEvent.click(stage);

    expect(stage.style.transform).toContain("translate(40px, 30px)");
    expect(stage.style.transform).toContain("scale(2)");
  });

  it("does not pan an image that is only fitted", () => {
    open();
    const stage = screen.getByTestId("lightbox-image");

    fireEvent.mouseDown(stage, { clientX: 100, clientY: 100 });
    fireEvent.mouseMove(window, { clientX: 200, clientY: 200 });

    expect(stage.style.transform).toContain("translate(0px, 0px)");
  });

  it("closes when the backdrop itself is clicked, not the picture", () => {
    const { onClose } = open();

    fireEvent.mouseDown(screen.getByTestId("lightbox-image"));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.mouseDown(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe("focus and the page behind", () => {
  it("takes focus, locks the page's scroll, then gives both back", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    expect(document.activeElement).toBe(opener);

    const { view } = open();

    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close" }));
    expect(document.body.style.overflow).toBe("hidden");

    view.unmount();

    expect(document.activeElement).toBe(opener);
    expect(document.body.style.overflow).toBe("");
    opener.remove();
  });

  it("keeps Tab inside the overlay", () => {
    open();
    const thumbs = screen.getAllByRole("button", { name: /\.(png|jpg|webp)$/ });
    const last = thumbs[thumbs.length - 1]!;
    last.focus();

    fireEvent.keyDown(document, { key: "Tab" });

    // Zoom in, not zoom out: the first control is disabled while the image is
    // fitted, and focus() on a disabled button would leave focus where it was.
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Zoom in" }));
  });

  it("wraps backwards too", () => {
    open();
    const first = screen.getByRole("button", { name: "Zoom in" });
    first.focus();

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });

    const thumbs = screen.getAllByRole("button", { name: /\.(png|jpg|webp)$/ });
    expect(document.activeElement).toBe(thumbs[thumbs.length - 1]);
  });
});

describe("orientation", () => {
  it("says which image this is and how many there are", () => {
    open({ index: 1 });
    expect(screen.getByText("2 of 3")).toBeTruthy();
    expect(screen.getByRole("dialog").getAttribute("aria-label")).toBe(
      "Image gallery: two.jpg",
    );
  });

  it("marks the current thumbnail in the filmstrip", () => {
    open({ index: 1 });
    // By role, not by alt: the stage image carries the same alt text.
    const current = screen.getByRole("button", { name: "two.jpg" });
    expect(current.getAttribute("aria-current")).toBe("true");
  });

  it("offers the original for download from the gallery", () => {
    open({ index: 1 });
    expect(screen.getByRole("link", { name: "Download" }).getAttribute("href")).toBe(
      "/ext/files/f_two?download=1",
    );
  });
});
