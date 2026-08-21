/**
 * Which bytes a preview asks for, and which files may appear in the gallery
 * (spec 011).
 *
 * Both questions have a wrong answer that looks right. Asking for the thumbnail
 * and then magnifying it magnifies the thumbnail's blur, which says nothing about
 * the scan the reader opened it to judge; and putting a .docx's thumbnail in a
 * gallery of images makes the gallery a gallery of something else.
 */

import type { FileRecord } from "@/lib/api/schemas";

/** The inline-renderable bytes route (spec 007 §7.3).
 *
 * `original` prefers the file's own pixels over the client-supplied thumbnail. The
 * server still falls back to the thumbnail when the type is not one a browser may
 * render inline, so this never turns a working preview into a 404.
 */
export function previewUrl(fileId: string, options: { original?: boolean } = {}): string {
  const base = `/ext/files/${encodeURIComponent(fileId)}/preview`;
  return options.original ? `${base}?original=1` : base;
}

/** Images only — what the gallery may show.
 *
 * `inline_renderable` is the server's decision, sniffed from the bytes, and it
 * carries the SVG exclusion: an .svg is an image format that is also a document
 * format, and inline from this origin its script would run with the reader's
 * session. `has_preview` deliberately does not count — a thumbnail attached to a
 * .docx is not an image file. A file whose blob has been pruned is excluded too,
 * rather than contributing a broken frame the reader has to interpret.
 */
export function isGalleryImage(file: FileRecord): boolean {
  return (
    file.inline_renderable &&
    file.media_type.startsWith("image/") &&
    file.blob_present !== false
  );
}
