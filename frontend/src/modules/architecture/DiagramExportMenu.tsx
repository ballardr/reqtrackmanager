/**
 * Module: modules/architecture/DiagramExportMenu
 *
 * The "Export" menu button of a diagram editor, shared by the block diagram and the state machine diagram: PNG and SVG
 * images, and Mermaid text to download or copy. The editor passes `useDiagramExport`'s `exportDiagram` as `onExport`.
 */
import { MenuButton } from "../../components/MenuButton";
import type { DiagramExportKind } from "./diagramExport";

/** The Export menu button: PNG and SVG images, and Mermaid text to download or copy. */
export function DiagramExportMenu({ disabled, onExport }: { disabled: boolean; onExport: (kind: DiagramExportKind) => void }) {
  return (
    <MenuButton
      label="Export" menuLabel="Export diagram" disabled={disabled}
      items={[
        { label: "PNG image", group: "Image", onSelect: () => onExport("png") },
        { label: "SVG image", group: "Image", onSelect: () => onExport("svg") },
        { label: "Download Mermaid text", key: "mermaid", group: "Text", onSelect: () => onExport("mermaid") },
        { label: "Copy Mermaid text", key: "copy-mermaid", group: "Text", onSelect: () => onExport("copy-mermaid") },
      ]}
    />
  );
}
