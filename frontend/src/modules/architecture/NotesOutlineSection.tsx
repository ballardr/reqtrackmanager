/**
 * Module: modules/architecture/NotesOutlineSection
 *
 * The "Notes" section of both diagram editors' Outline tab: every annotation note as a button (its title and text shortened),
 * and under each its leaders ("Leader 1 · Points at ELM-001 Gateway"). Selecting one selects it on the canvas and in the
 * Selection card. What a leader points at is in words the caller supplies, since a block diagram's targets are elements and
 * connections and a state machine diagram's are states and transitions.
 */
import { CollapsibleSection } from "../../components/CollapsibleSection";
import type { GraphCanvasSelection } from "../../components/GraphCanvas";
import { NOTE_NODE_PREFIX, noteSummary, type EditorLeader, type EditorNote } from "./noteModel";

/**
 * @param notes The diagram's notes; nothing is drawn when there are none.
 * @param sectionKey The key the section's open state is remembered under.
 * @param help What a note is on this diagram type (the section's tooltip).
 * @param selection What is selected on the canvas, or null.
 * @param onSelect Selects a note (a node) or a leader.
 * @param pointsAt A leader's target in words, with " (not drawn)" when it is hidden.
 */
export function NotesOutlineSection({
  notes, sectionKey, help, selection, onSelect, pointsAt,
}: {
  notes: readonly EditorNote[];
  sectionKey: string;
  help: string;
  selection: GraphCanvasSelection | null;
  onSelect: (selection: GraphCanvasSelection) => void;
  pointsAt: (leader: EditorLeader) => string;
}) {
  if (notes.length === 0) return null;
  const isSelected = (kind: GraphCanvasSelection["kind"], id: string) => selection?.kind === kind && selection.id === id;
  return (
    <CollapsibleSection sectionKey={sectionKey} title="Notes" help={help} variant="plain" summary={String(notes.length)}>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {notes.map((n) => (
          <li key={n.key}>
            <button
              type="button" className={isSelected("node", NOTE_NODE_PREFIX + n.key) ? "btn btn-sm btn-primary" : "btn btn-sm"}
              aria-current={isSelected("node", NOTE_NODE_PREFIX + n.key) ? "true" : undefined}
              onClick={() => onSelect({ kind: "node", id: NOTE_NODE_PREFIX + n.key })}
            >
              {noteSummary(n)}
            </button>
            {n.leaders.length > 0 && (
              <ul style={{ listStyle: "none", margin: 0, paddingLeft: "var(--space-4)" }} aria-label="Leaders">
                {n.leaders.map((l, i) => (
                  <li key={l.key}>
                    <button
                      type="button" className={isSelected("leader", l.key) ? "btn btn-sm btn-primary" : "btn btn-sm"}
                      aria-current={isSelected("leader", l.key) ? "true" : undefined}
                      onClick={() => onSelect({ kind: "leader", id: l.key })}
                    >
                      Leader {i + 1}
                    </button>
                    <span className="text-muted"> · Points at {pointsAt(l)}</span>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </CollapsibleSection>
  );
}
