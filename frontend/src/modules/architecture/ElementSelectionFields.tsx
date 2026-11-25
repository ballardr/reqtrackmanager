/**
 * Module: modules/architecture/ElementSelectionFields
 *
 * The Selection card's editable view of one element: the shared field group (`ElementFields`, also the edit dialog's) edited in
 * place and stored when the focus leaves the group or Save is pressed, quoting the element's version as every other element edit
 * does. A name left blank is not stored and says so; another save's changes to a field the person has not touched are taken in,
 * and a field being edited is kept.
 *
 * Design decisions:
 * - The draft and its commit are the shared `useSelectionDraft`; an element is stored at once, not with the drawing.
 * - The Save button (`SelectionSaveButton`) is on the card's heading line, always present and disabled while nothing
 *   has changed, so the header keeps its size as the person types.
 * - A component or category, tags and ports are separate controls of the card (each stored on its own), not part of this draft.
 */
import { useEffect, useRef } from "react";

import type { OrgUser } from "../../api/types";
import { FormGrid } from "../../components/FormGrid";
import { useLatest } from "../../hooks/useLatest";
import { diffElementFields, subtreeIds, valuesFromElement } from "./architectureFields";
import { ElementFields } from "./ElementFields";
import type { ArchitectureElement, ArchitectureSymbol, ElementFieldValues, ElementType } from "./types";
import { isOutOfUse } from "./types";
import { SelectionSaveButton } from "./SelectionSaveButton";
import { useSelectionDraft } from "./useSelectionDraft";

/**
 * @param element The selected element as last read.
 * @param elementTypes The types that may be chosen.
 * @param candidates The project's own elements, from which the parent choices are taken.
 * @param symbols The symbols that may be chosen.
 * @param symbolUrl The API path of a symbol's content.
 * @param orgUsers Organisation members offered as owner.
 * @param organizationId The owning organisation.
 * @param projectId The owning project.
 * @param autoFocusName True to select the name when the card first appears (an element just added).
 * @param onFocused Called once the name has taken the focus, so the request is not repeated.
 * @param onSave Stores the changed fields; resolves true when stored.
 * @param onSymbolsChanged Called after the symbol picker uploads a symbol, so the caller reloads `symbols`.
 */
export function ElementSelectionFields({
  element, elementTypes, candidates, symbols, symbolUrl, orgUsers, organizationId, projectId, autoFocusName, onFocused, onSave, onSymbolsChanged,
}: {
  element: ArchitectureElement;
  elementTypes: ElementType[];
  candidates: ArchitectureElement[];
  symbols: ArchitectureSymbol[];
  symbolUrl: (symbolId: string) => string;
  orgUsers: OrgUser[];
  organizationId: string;
  projectId: string;
  autoFocusName: boolean;
  onFocused: () => void;
  onSave: (changed: Partial<ElementFieldValues>) => Promise<boolean>;
  onSymbolsChanged?: () => void;
}) {
  const { draft, set, hasChanges, refused: nameMissing, commit } = useSelectionDraft<ElementFieldValues>({
    stored: valuesFromElement(element), diff: diffElementFields, normalise: (v) => ({ ...v, name: v.name.trim() }),
    refuse: (v) => v.name.trim() === "", onSave,
  });
  const focusDone = useLatest(onFocused);
  const askedFocus = useRef(autoFocusName);
  useEffect(() => { if (askedFocus.current) focusDone.current(); }, [focusDone]);

  const excluded = subtreeIds(element.id, candidates);
  const parents = candidates.filter((e) => !excluded.has(e.id) && !isOutOfUse(e.status));

  return (
    <div
      className="stack" role="group" aria-label="Element details"
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) void commit(); }}
    >
      <FormGrid minColumn="14rem">
        <ElementFields
          values={draft} onChange={set} elementTypes={elementTypes} parents={parents} symbols={symbols} symbolUrl={symbolUrl}
          orgUsers={orgUsers} organizationId={organizationId} projectId={projectId} saved={element} autoFocusName={autoFocusName}
          onSymbolsChanged={onSymbolsChanged}
        />
      </FormGrid>
      {nameMissing && <p role="alert" style={{ color: "var(--color-danger)" }}>A name is required.</p>}
      <SelectionSaveButton label="Save element" disabled={!hasChanges} onSave={() => void commit()} />
    </div>
  );
}
