// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Magnifier } from "@/components/files/Magnifier";

/**
 * The lens (spec 011 §11.2).
 *
 * Every assertion here is arithmetic that is invisible when wrong: a lens with a
 * mis-signed offset still looks like a magnifier, it just shows a region the
 * pointer is not on. So the background offsets are computed by hand and pinned
 * rather than eyeballed in a browser.
 *
 * The frame is 400×300 on screen; the lens is 176px across, so its half is 88.
 */

const RECT = { left: 0, top: 0, right: 400, bottom: 300, width: 400, height: 300 };

beforeEach(() => {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
    ...RECT,
    x: 0,
    y: 0,
    toJSON: () => RECT,
  } as DOMRect);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function lensOf() {
  return screen.queryByTestId("zoom-lens");
}

describe("the lens", () => {
  it("is absent until the pointer is over the image", () => {
    render(<Magnifier src="/ext/files/f_abc/preview?original=1" alt="Preview of a.png" zoom={2} />);
    expect(lensOf()).toBeNull();
  });

  it("magnifies the point under the pointer", () => {
    render(<Magnifier src="/p.png" alt="Preview of a.png" zoom={2} />);
    const frame = screen.getByAltText("Preview of a.png").parentElement!;

    fireEvent.mouseMove(frame, { clientX: 200, clientY: 150 });

    const lens = lensOf()!;
    // The image is drawn at 2× into an 800×600 plane...
    expect(lens.style.backgroundSize).toBe("800px 600px");
    // ...and the window onto it is centred on the pointer: 200×2 − 88 = 312.
    expect(lens.style.backgroundPosition).toBe("-312px -212px");
    // The window itself sits under the pointer, not beside it.
    expect(lens.style.left).toBe("112px");
    expect(lens.style.top).toBe("62px");
  });

  it("never shows blank space past the edge of the image", () => {
    // Top-left corner: an unclamped offset would be 0×2 − 88 = −88, which slides
    // the magnified image inward and puts empty lens where the image should be.
    render(<Magnifier src="/p.png" alt="Preview of a.png" zoom={2} />);
    const frame = screen.getByAltText("Preview of a.png").parentElement!;

    fireEvent.mouseMove(frame, { clientX: 0, clientY: 0 });

    // "-0px", which the DOM serialises without the sign.
    expect(lensOf()!.style.backgroundPosition).toBe("0px 0px");
  });

  it("clamps at the far edge too", () => {
    render(<Magnifier src="/p.png" alt="Preview of a.png" zoom={2} />);
    const frame = screen.getByAltText("Preview of a.png").parentElement!;

    fireEvent.mouseMove(frame, { clientX: 400, clientY: 300 });

    // 800 − 176 = 624 across, 600 − 176 = 424 down.
    expect(lensOf()!.style.backgroundPosition).toBe("-624px -424px");
  });

  it("goes away when the pointer leaves", () => {
    render(<Magnifier src="/p.png" alt="Preview of a.png" zoom={2} />);
    const frame = screen.getByAltText("Preview of a.png").parentElement!;

    fireEvent.mouseMove(frame, { clientX: 200, clientY: 150 });
    expect(lensOf()).not.toBeNull();

    fireEvent.mouseLeave(frame);
    expect(lensOf()).toBeNull();
  });
});

describe("honesty about resolution", () => {
  it("says when the lens has magnified past the file's own pixels", () => {
    // 600 real pixels drawn 400 wide means 1:1 arrives at 1.5×. At 3× the lens is
    // interpolating: still bigger, no longer more detailed.
    render(<Magnifier src="/p.png" alt="Preview of a.png" zoom={3} />);
    const image = screen.getByAltText("Preview of a.png");
    Object.defineProperty(image, "naturalWidth", { value: 600, configurable: true });
    Object.defineProperty(image, "naturalHeight", { value: 450, configurable: true });
    fireEvent.load(image);

    fireEvent.mouseMove(image.parentElement!, { clientX: 200, clientY: 150 });

    expect(lensOf()!.textContent).toBe("3× · past 1:1");
  });

  it("stays quiet while the lens is still revealing detail", () => {
    render(<Magnifier src="/p.png" alt="Preview of a.png" zoom={2} />);
    const image = screen.getByAltText("Preview of a.png");
    Object.defineProperty(image, "naturalWidth", { value: 2400, configurable: true });
    Object.defineProperty(image, "naturalHeight", { value: 1800, configurable: true });
    fireEvent.load(image);

    fireEvent.mouseMove(image.parentElement!, { clientX: 200, clientY: 150 });

    expect(lensOf()!.textContent).toBe("2×");
  });

  it("claims nothing when the image's own size is unknown", () => {
    // naturalWidth is 0 before the decode lands. Reporting "past 1:1" from that
    // would be a claim about a file nothing has measured.
    render(<Magnifier src="/p.png" alt="Preview of a.png" zoom={6} />);
    const image = screen.getByAltText("Preview of a.png");
    fireEvent.load(image);

    fireEvent.mouseMove(image.parentElement!, { clientX: 200, clientY: 150 });

    expect(lensOf()!.textContent).toBe("6×");
  });
});

describe("opening the gallery", () => {
  it("is a button when there is a gallery to open", () => {
    const onOpen = vi.fn();
    render(
      <Magnifier
        src="/p.png"
        alt="Preview of a.png"
        zoom={2}
        onOpen={onOpen}
        openLabel="Open a.png in the gallery"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open a.png in the gallery" }));

    expect(onOpen).toHaveBeenCalledOnce();
  });

  it("is not a button when there is not", () => {
    // A thumbnail belonging to a .docx magnifies fine and has no gallery to open.
    // Presenting it as a control would promise a click that does nothing.
    render(<Magnifier src="/p.png" alt="Preview of a.docx" zoom={2} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
