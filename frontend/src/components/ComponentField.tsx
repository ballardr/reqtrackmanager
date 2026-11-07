/**
 * Module: components/ComponentField
 *
 * The "Components" field of a create form: choose the components and categories the new record starts in.
 * Nothing is written here; the choice is held for `useCommitTags`, which applies it once the record exists, the
 * same contract as `TagField` and `QuickLinkField` (`hooks/pendingPlacements`).
 *
 * It asks the server about a record that does not exist yet (`DRAFT_ARTEFACT_ID`), so the caller's authority
 * is the one that will apply, and it renders nothing when the caller may not place this kind of record (a
 * requirement keeps its own component), the project has no components, or the read fails: a form never offers a
 * field that would be refused. `TagField` renders it, so every create form that has tags has this too.
 */
import { useEffect, useId, useState } from "react";

import { DRAFT_ARTEFACT_ID } from "../api/artefactLinks";
import {
  recordPlacementsApi, type PlacementPair, type PlacementTree, type RecordPlacementsApi,
} from "../api/placements";
import { useStrings } from "../context/TerminologyContext";
import { setPendingPlacements } from "../hooks/pendingPlacements";
import { FieldCaption } from "./FieldHelp";
import { PlacementPicker } from "./PlacementPicker";

/**
 * @param projectId The project the record is being created in.
 * @param artefactType The registered type of the record being created.
 * @param api Injectable calls (stories pass a fake).
 */
export function ComponentField({
  projectId, artefactType, api = recordPlacementsApi,
}: { projectId: string; artefactType: string; api?: RecordPlacementsApi }) {
  const strings = useStrings();
  const controlId = useId();
  const [tree, setTree] = useState<PlacementTree | null>(null);
  const [value, setValue] = useState<PlacementPair[]>([]);

  useEffect(() => {
    let active = true;
    Promise.all([api.get(projectId, artefactType, DRAFT_ARTEFACT_ID), api.tree(projectId)])
      .then(([draft, loaded]) => active && setTree(draft.can_edit && !draft.managed_on_record ? loaded : null))
      .catch(() => active && setTree(null));
    return () => {
      active = false;
    };
  }, [api, projectId, artefactType]);

  // A form that closes (saved or cancelled) leaves nothing behind for the next create of this type.
  useEffect(() => () => setPendingPlacements(projectId, artefactType, []), [projectId, artefactType]);

  if (!tree || tree.components.length === 0) return null;
  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <FieldCaption htmlFor={controlId} label={strings.placements.label} help={strings.help.recordComponents} />
      <PlacementPicker
        id={controlId}
        tree={tree}
        value={value}
        onChange={(next) => {
          setValue(next);
          setPendingPlacements(projectId, artefactType, next);
        }}
      />
    </div>
  );
}
