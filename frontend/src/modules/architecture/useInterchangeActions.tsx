/**
 * Module: modules/architecture/useInterchangeActions
 *
 * The project's architecture interchange as one parent row ("Interchange") of the Elements page's actions menu: download
 * the architecture as a JSON file or a Structurizr DSL workspace, and import a JSON file (`InterchangeImportDialog`).
 *
 * Responsibilities:
 * - Download either file from the server and save it under the name the server chose, with a toast for the outcome.
 * - Open the import dialog and tell the page when an import has added records, so the list reloads.
 */
import { useMemo, useState, type ReactNode } from "react";

import type { ActionMenuItem } from "../../components/ActionMenu";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { downloadBlob } from "../../utils/download";
import { projectInterchangeApi } from "./api";
import { InterchangeImportDialog } from "./InterchangeImportDialog";

/**
 * @param projectId The project whose architecture is exchanged.
 * @param onImported Called after an import has added records.
 * @returns `menuItems` (one "Interchange" parent row for the page's actions menu) and `dialog` (the import dialog, rendered once).
 */
export function useInterchangeActions(projectId: string, onImported: () => void): { menuItems: ActionMenuItem[]; dialog: ReactNode } {
  const { showToast } = useToast();
  const [importing, setImporting] = useState(false);

  const menuItems = useMemo<ActionMenuItem[]>(() => {
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
    return [{
      key: "interchange", label: "Interchange", onSelect: () => undefined,
      children: [
        { label: "Export JSON file", key: "export-json", onSelect: () => void download("json") },
        { label: "Export Structurizr DSL", key: "export-dsl", onSelect: () => void download("dsl") },
        { label: "Import JSON file…", key: "import-json", onSelect: () => setImporting(true) },
      ],
    }];
  }, [projectId, showToast]);

  const dialog: ReactNode = importing && (
    <InterchangeImportDialog
      projectId={projectId} onClose={() => setImporting(false)}
      onImported={() => { setImporting(false); onImported(); }}
    />
  );
  return { menuItems, dialog };
}
