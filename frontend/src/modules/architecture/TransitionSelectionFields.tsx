/**
 * Module: modules/architecture/TransitionSelectionFields
 *
 * The Selection card's editable view of one transition: the shared field group (`TransitionFieldGroup`) edited in place and stored
 * when the focus leaves the group or Save is pressed, quoting the diagram's version as every other transition edit does. Another
 * save's changes to a field the person has not touched are taken in, and a field being edited is kept.
 *
 * Design decisions:
 * - The draft and its commit are the shared `useSelectionDraft`, the same as a state's card.
 * - The Save button is always present and disabled while nothing has changed, so the card does not change size as the person types.
 */
import { useEffect, useRef } from "react";

import { FormGrid } from "../../components/FormGrid";
import { useLatest } from "../../hooks/useLatest";
import { TransitionFieldGroup, type TransitionFocusField } from "./TransitionFieldGroup";
import { diffTransitionFields, valuesFromTransition } from "./transitionFields";
import type { ArchitectureState, StateTransition, TransitionFieldValues } from "./types";
import { useSelectionDraft } from "./useSelectionDraft";

/**
 * @param transition The selected transition as last read.
 * @param states The diagram's states, for the two end pickers.
 * @param autoFocus The field to put the cursor in when the card first appears (a transition just added); none when omitted.
 * @param onFocused Called once that field has taken the focus, so the request is not repeated.
 * @param onSave Stores the changed fields; resolves true when stored.
 */
export function TransitionSelectionFields({
  transition, states, autoFocus, onFocused, onSave,
}: {
  transition: StateTransition;
  states: ArchitectureState[];
  autoFocus?: TransitionFocusField;
  onFocused: () => void;
  onSave: (changed: Partial<TransitionFieldValues>) => Promise<boolean>;
}) {
  const { draft, set, hasChanges, commit } = useSelectionDraft<TransitionFieldValues>({
    stored: valuesFromTransition(transition), diff: diffTransitionFields, onSave,
  });
  const focusDone = useLatest(onFocused);
  const askedFocus = useRef(autoFocus !== undefined);

  // The field takes the focus as the group mounts (its `autoFocus`); the page is then told, so a later mount does not repeat it.
  useEffect(() => { if (askedFocus.current) focusDone.current(); }, [focusDone]);

  return (
    <div
      className="stack" role="group" aria-label="Transition details"
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) void commit(); }}
    >
      <FormGrid minColumn="14rem">
        <TransitionFieldGroup states={states} values={draft} onChange={set} autoFocus={autoFocus} />
      </FormGrid>
      <button
        type="button" className="btn btn-sm" style={{ alignSelf: "flex-start" }}
        disabled={!hasChanges} onClick={() => void commit()} aria-label="Save transition"
      >
        Save
      </button>
    </div>
  );
}
