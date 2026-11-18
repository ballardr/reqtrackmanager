/**
 * Module: modules/architecture/useDiagramExport
 *
 * The Export of a diagram editor, shared by the block diagram and the state machine diagram (`DiagramExportMenu` offers it).
 *
 * Responsibilities:
 * - `useDiagramExport`: saves a pending drawing first (an export is of the stored diagram), then downloads a PNG or SVG
 *   image or a Mermaid text file, or copies the Mermaid text, and tells the person the outcome.
 *
 * Design decisions:
 * - The editor supplies the two loaders (which call its own endpoints), so the hook knows nothing of either diagram type;
 *   a PNG is the server's SVG drawn in the browser, as in the block diagram's export.
 */
import { useState } from "react";

import { toErrorMessage, useToast } from "../../context/ToastContext";
import { downloadBlob } from "../../utils/download";
import { svgToPngBlob } from "../../utils/svgToPng";
import { exportFileName, type DiagramExportKind } from "./diagramExport";

/** What the hook needs from an editor. */
export interface DiagramExportSource {
  /** The record's code (`DGM-001`, `SMD-001`) and name, which make the file name. */
  code: string;
  name: string;
  /** Stores a pending drawing; resolves false when it could not be stored (the export is then not made). */
  ensureSaved: () => Promise<boolean>;
  /** The saved diagram as the server's SVG document. */
  loadSvg: () => Promise<string>;
  /** The saved diagram as the server's Mermaid text. */
  loadMermaid: () => Promise<string>;
}

/**
 * @param source The record and how to read its exports.
 * @returns `exporting` (true while a call is in progress) and `exportDiagram`, which makes one kind of export and toasts the outcome.
 */
export function useDiagramExport(source: DiagramExportSource | null) {
  const { showToast } = useToast();
  const [exporting, setExporting] = useState(false);

  async function exportDiagram(kind: DiagramExportKind) {
    if (!source || exporting) return;
    setExporting(true);
    try {
      if (!(await source.ensureSaved())) return;
      const file = (extension: string) => exportFileName(source.code, source.name, extension);
      if (kind === "svg") {
        downloadBlob(new Blob([await source.loadSvg()], { type: "image/svg+xml" }), file("svg"));
      } else if (kind === "png") {
        downloadBlob(await svgToPngBlob(await source.loadSvg()), file("png"));
      } else if (kind === "mermaid") {
        downloadBlob(new Blob([await source.loadMermaid()], { type: "text/plain" }), file("mmd"));
      } else {
        await navigator.clipboard.writeText(await source.loadMermaid());
        showToast("Mermaid text copied.");
        return;
      }
      showToast("Diagram exported.");
    } catch (err) {
      showToast(toErrorMessage(err, "Could not export the diagram."), "error");
    } finally {
      setExporting(false);
    }
  }

  return { exporting, exportDiagram };
}
