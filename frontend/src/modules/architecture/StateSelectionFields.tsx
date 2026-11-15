/**
 * Module: modules/architecture/StateSelectionFields
 *
 * The Selection card's editable view of one state: the shared field group (`StateFieldGroup`) edited in place and stored when the
 * focus leaves the group or Save is pressed, quoting the diagram's version as every other state edit does. A name left blank is
 * not stored and says so; another save's changes to a field the person has not touched are taken in, and a field being edited is
 * kept.
 *
 * Design decisions:
 * - The draft and its commit are the shared `useSelectionDraft`; content is stored at once, not with the drawing (the findings and
 *   the state's code come from the server).
 * - The Save button is always present and disabled while nothing has changed, so the card does not change size as the person types.
 */
import { useEffect, useRef } from "react";

import { FormGrid } from "../../components/FormGrid";
import { useLatest } from "../../hooks/useLatest";
import { StateFieldGroup } from "./StateFieldGroup";
import { isMarkerKind } from "./stateMachineModel";
import { diffStateFields, valuesFromState } from "./stateFields";
import type { ArchitectureState, StateFieldValues } from "./types";
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
    stored: valuesFromState(state), diff: diffStateFields, normalise: (v) => ({ ...v, name: v.name.trim(), label: isMarkerKind(v.kind) ? v.label.trim() : "" }),
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
      <button
        type="button" className="btn btn-sm" style={{ alignSelf: "flex-start" }}
        disabled={!hasChanges} onClick={() => void commit()}
      >
        Save state
      </button>
    </div>
  );
}
