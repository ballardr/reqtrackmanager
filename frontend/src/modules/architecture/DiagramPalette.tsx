/**
 * Module: modules/architecture/DiagramPalette
 *
 * The editor's "Add" card: the element types as draggable tiles (drop one on the canvas to create an element there, or press
 * it to create one at the next free place), plus "Add existing elements" and "Add note". Dragging is only one way in: every
 * tile is a button, so the palette is usable from the keyboard.
 */
import { GRAPH_DROP_MIME } from "../../components/GraphCanvas";
import { DetailCard } from "../../components/DetailCard";
import { PALETTE_TYPE_PREFIX } from "./diagramToggles";
import { DOMAIN_LABEL, type ElementType } from "./types";

/**
 * @param elementTypes The types that may be created.
 * @param disabled True when the diagram cannot be edited (read-only).
 * @param onAddType Called when a tile is pressed.
 * @param onAddExisting Called by "Add existing elements".
 * @param onAddNote Called by "Add note".
 */
export function DiagramPalette({
  elementTypes, disabled, onAddType, onAddExisting, onAddNote,
}: {
  elementTypes: ElementType[];
  disabled: boolean;
  onAddType: (typeId: string) => void;
  onAddExisting: () => void;
  onAddNote: () => void;
}) {
  return (
    <DetailCard heading="Add to diagram">
      <div className="row" style={{ gap: "var(--space-2)" }}>
        <button type="button" className="btn btn-sm" disabled={disabled} onClick={onAddExisting}>Add existing elements</button>
        <button type="button" className="btn btn-sm" disabled={disabled} onClick={onAddNote}>Add note</button>
      </div>
      <div role="group" aria-label="New element by type" className="stack" style={{ gap: "var(--space-1)" }}>
        {elementTypes.map((t) => (
          <button
            key={t.id} type="button" className="btn btn-sm" disabled={disabled} draggable={!disabled}
            style={{ justifyContent: "flex-start", borderLeft: `4px solid ${t.color_light ?? "var(--color-primary)"}` }}
            aria-label={`New ${t.name}`} title={`${t.name} (${DOMAIN_LABEL[t.domain]})`}
            onClick={() => onAddType(t.id)}
            onDragStart={(event) => {
              event.dataTransfer.setData(GRAPH_DROP_MIME, PALETTE_TYPE_PREFIX + t.id);
              event.dataTransfer.effectAllowed = "copy";
            }}
          >
            {t.name}
          </button>
        ))}
      </div>
    </DetailCard>
  );
}
