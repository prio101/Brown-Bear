import { FileBrowser } from "@/components/FileBrowser";
import { Nav } from "@/components/Nav";
import { Panel, PanelBody } from "@/components/Panel";
import { Text } from "@/components/Text";
import { getFiles } from "@/lib/api/endpoints";
import { toPanelState } from "@/lib/api/panel";
import { bytes } from "@/lib/format";

/**
 * Ingested files (spec 007).
 *
 * The list is fetched server-side like every other page. The extracted text is
 * not: it is fetched per file on selection, because a corpus of extractions would
 * be megabytes of payload for a list nobody reads in full.
 */

export default async function FilesPage() {
  const files = await getFiles({ limit: 200 });

  const state = toPanelState(
    files,
    (data) => data.files.length === 0,
    "No files yet. A machine sends one with POST /ext/files, carrying the bytes and the text it extracted from them.",
  );

  return (
    <div className="bb-shell">
      <Nav current="/files" />
      <main className="bb-page">
        <header style={{ marginBottom: "var(--bb-space-6)" }}>
          <Text role="headline-medium" as="h1">
            Files
          </Text>
          <Text role="body-medium" style={{ color: "var(--bb-on-surface-variant)" }}>
            Documents and images stored here, with the text a client extracted from
            them. Extraction happens on the machine that has the file — Brown Bear
            records what produced it but cannot verify it, so the extractor is shown
            beside the text.
          </Text>
          {files.ok ? (
            <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
              {`${files.data.total} files · ${bytes(files.data.store_bytes)} on disk`}
            </Text>
          ) : null}
        </header>

        <Panel title="Stored files">
          <PanelBody state={state}>{(data) => <FileBrowser initial={data.files} />}</PanelBody>
        </Panel>
      </main>
    </div>
  );
}
