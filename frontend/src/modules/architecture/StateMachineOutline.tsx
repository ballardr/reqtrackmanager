/**
 * Module: modules/architecture/StateMachineOutline
 *
 * The state machine diagram editor's "Outline" tab: the text alternative to the canvas. The states are a tree (a composite
 * state holds its children), the transitions a table (from, to, event, guard, action), and the findings follow. It follows the
 * page: it is built from the model and the drawing being edited, so a state moved inside another shows under it before Save.
 *
 * Responsibilities:
 * - List every state with its code, kind and entry, exit and do lines, nested as drawn.
 * - List every transition with the codes and names of its two states; selecting a row selects it on the canvas and in the
 *   Selection card.
 *
 * Design decisions:
 * - Built on the shared `TreeView` and table styles; every row is a real button, so the outline is operable from the keyboard.
 */
import { useMemo } from "react";

import { CollapsibleSection } from "../../components/CollapsibleSection";
import { DetailCard } from "../../components/DetailCard";
import type { GraphCanvasSelection } from "../../components/GraphCanvas";
import { TreeView } from "../../components/TreeView";
import { actionLines, stateTree, type StateMachineLayout } from "./stateMachineModel";
import { useStateLabel } from "./useStateLabel";
import { STATE_KIND_LABEL, type StateMachineModel } from "./types";

/**
 * @param model The model as read.
 * @param layout The drawing being edited (its nesting is what the tree shows).
 * @param selection What is selected on the canvas, or null.
 * @param onSelect Selects a state (a node) or a transition (an edge).
 */
export function StateMachineOutline({
  model, layout, selection, onSelect,
}: {
  model: StateMachineModel;
  layout: StateMachineLayout;
  selection: GraphCanvasSelection | null;
  onSelect: (selection: GraphCanvasSelection) => void;
}) {
  const stateName = useStateLabel().label;
  const tree = useMemo(() => stateTree(model, layout), [model, layout]);
  const states = new Map(model.states.map((s) => [s.id, s]));
  const isSelected = (kind: GraphCanvasSelection["kind"], id: string) => selection?.kind === kind && selection.id === id;
  const { states: stateCount, transitions: transitionCount } = { states: model.states.length, transitions: model.transitions.length };
  return (
    <DetailCard heading="Outline">
      <p className="text-muted">
        {stateCount} {stateCount === 1 ? "state" : "states"}, {transitionCount} {transitionCount === 1 ? "transition" : "transitions"}.
      </p>
      <CollapsibleSection sectionKey="architecture_state_outline_states" title="States" variant="plain" summary={String(stateCount)}>
        <TreeView
          nodes={tree}
          nodeLabel={(node) => stateName(node.state)}
          emptyText="This state machine diagram has no states yet."
          renderNode={(node) => (
            <span className="row" style={{ gap: "var(--space-2)", alignItems: "baseline", flexWrap: "wrap" }}>
              <button
                type="button" className={isSelected("node", node.id) ? "btn btn-sm btn-primary" : "btn btn-sm"}
                aria-current={isSelected("node", node.id) ? "true" : undefined} onClick={() => onSelect({ kind: "node", id: node.id })}
              >
                {stateName(node.state)}
              </button>
              <span className="text-muted">{STATE_KIND_LABEL[node.state.kind]}</span>
              {actionLines(node.state) && <span className="text-muted" style={{ whiteSpace: "pre-line" }}>{actionLines(node.state)}</span>}
            </span>
          )}
        />
      </CollapsibleSection>
      <CollapsibleSection sectionKey="architecture_state_outline_transitions" title="Transitions" variant="plain" summary={String(transitionCount)}>
        {transitionCount === 0 ? (
          <p className="text-muted">This state machine diagram has no transitions yet.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="table" aria-label="Transitions">
              <thead>
                <tr>
                  <th scope="col">From</th>
                  <th scope="col">To</th>
                  <th scope="col">Event</th>
                  <th scope="col">Guard</th>
                  <th scope="col">Action</th>
                </tr>
              </thead>
              <tbody>
                {model.transitions.map((t) => {
                  const from = states.get(t.source_state_id);
                  const to = states.get(t.target_state_id);
                  return (
                    <tr key={t.id}>
                      <td>
                        <button
                          type="button" className={isSelected("edge", t.id) ? "btn btn-sm btn-primary" : "btn btn-sm"}
                          aria-current={isSelected("edge", t.id) ? "true" : undefined}
                          aria-label={`Transition from ${from ? stateName(from) : t.source_state_code} to ${to ? stateName(to) : t.target_state_code}`}
                          onClick={() => onSelect({ kind: "edge", id: t.id })}
                        >
                          {from ? stateName(from) : t.source_state_code}
                        </button>
                      </td>
                      <td>{to ? stateName(to) : t.target_state_code}</td>
                      <td>{t.event || "—"}</td>
                      <td>{t.guard || "—"}</td>
                      <td>{t.action || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CollapsibleSection>
    </DetailCard>
  );
}
