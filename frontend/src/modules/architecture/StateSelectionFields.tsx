/**
 * Module: modules/architecture/StateSelectionFields
 *
 * The Selection card's editable view of one state: the shared `StateFieldGroup` edited in place and stored when focus leaves
 * the group or Save is pressed, quoting the diagram's version. A blank name is not stored and says so; other saves' changes to
 * untouched fields are taken in while a field being edited is kept.
 *
 * The draft and its commit are the shared `useSelectionDraft`; content is stored at once, not with the drawing. The Save
 * button (`SelectionSaveButton`) is always on the heading line, disabled while nothing has changed, so the header keeps its size.
 */
import { useEffect, useRef } from "react";

import { FormGrid } from "../../components/FormGrid";
import { useLatest } from "../../hooks/useLatest";
import { StateFieldGroup } from "./StateFieldGroup";
import { diffStateFields, normaliseStateValues, valuesFromState } from "./stateFields";
import type { ArchitectureState, StateFieldValues } from "./types";
import { SelectionSaveButton } from "./SelectionSaveButton";
import { useSelectionDraft } from "./useSelectionDraft";

/**
 * @param state The selected state as last read.
 * @param holdsStates True when the state has child states (it cannot become a marker).
 * @param autoFocusName True to put the cursor in the name when the card first appears (a state just added).
 * @param onFocused Called once the name has taken the focus, so the request is not repeated.
 * @param onSave Stores the changed fields; resolves true when stored.
 */
export function StateSelectionFields({
  state, holdsStates, autoFocusName, onFocused, onSave,
}: {
  state: ArchitectureState;
  holdsStates: boolean;
  autoFocusName: boolean;
  onFocused: () => void;
  onSave: (changed: Partial<StateFieldValues>) => Promise<boolean>;
}) {
  const { draft, set, hasChanges, refused: nameMissing, commit } = useSelectionDraft<StateFieldValues>({
    stored: valuesFromState(state), diff: diffStateFields, normalise: normaliseStateValues,
    refuse: (v) => v.name.trim() === "", onSave,
  });
  const focusDone = useLatest(onFocused);
  const askedFocus = useRef(autoFocusName);

  // The name takes the focus as the group mounts (its `autoFocus`); the page is then told, so a later mount does not repeat it.
  useEffect(() => { if (askedFocus.current) focusDone.current(); }, [focusDone]);

  return (
    <div
      className="stack" role="group" aria-label="State details"
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) void commit(); }}
    >
      <FormGrid minColumn="14rem">
        <StateFieldGroup values={draft} onChange={set} holdsStates={holdsStates} autoFocusName={autoFocusName} />
      </FormGrid>
      {nameMissing && <p role="alert" style={{ color: "var(--color-danger)" }}>A name is required.</p>}
      <SelectionSaveButton label="Save state" disabled={!hasChanges} onSave={() => void commit()} />
    </div>
  );
}
