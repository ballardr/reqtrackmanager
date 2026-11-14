/**
 * Module: modules/architecture/InterchangeMenu
 *
 * The "Interchange" menu button of the Elements list: download the project's architecture as a JSON file or a Structurizr
 * DSL workspace, and import a JSON file (`InterchangeImportDialog`).
 *
 * Responsibilities:
 * - Download either file from the server and save it under the name the server chose, with a toast for the outcome.
 * - Open the import dialog and tell the page when an import has added records, so the list reloads.
 */
import { useState } from "react";

import { MenuButton } from "../../components/MenuButton";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { downloadBlob } from "../../utils/download";
import { projectInterchangeApi } from "./api";
import { InterchangeImportDialog } from "./InterchangeImportDialog";

/**
 * @param projectId The project whose architecture is exchanged.
 * @param onImported Called after an import has added records.
 */
export function InterchangeMenu({ projectId, onImported }: { projectId: string; onImported: () => void }) {
  const { showToast } = useToast();
  const [importing, setImporting] = useState(false);
  const calls = projectInterchangeApi(projectId);

  async function download(kind: "json" | "dsl") {
    try {
      const blob = await (kind === "json" ? calls.exportJson() : calls.exportStructurizr());
      downloadBlob(blob, `architecture.${kind === "json" ? "json" : "dsl"}`);
      showToast(kind === "json" ? "JSON file exported." : "Structurizr file exported.");
    } catch (err) {
      showToast(toErrorMessage(err, "The export failed."), "error");
    }
  }

  return (
    <>
      <MenuButton
        label="Interchange" menuLabel="Interchange"
        items={[
          { label: "Export JSON file", key: "export-json", group: "Export", onSelect: () => void download("json") },
          { label: "Export Structurizr DSL", key: "export-dsl", group: "Export", onSelect: () => void download("dsl") },
          { label: "Import JSON file…", key: "import-json", group: "Import", onSelect: () => setImporting(true) },
        ]}
      />
      {importing && (
        <InterchangeImportDialog
          projectId={projectId} onClose={() => setImporting(false)}
          onImported={() => { setImporting(false); onImported(); }}
        />
      )}
    </>
  );
}
