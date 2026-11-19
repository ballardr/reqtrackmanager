/**
 * Module: hooks/pendingReferences
 *
 * The external references a create form has collected for a record that does not exist yet, handed from the form's
 * `ReferenceField` to the create path's `useCommitTags` without every form's `onSave` signature growing a
 * parameter. Keyed by project and record type, because a create form is open for one record type at a time; the
 * field clears its entry when it unmounts, so a cancelled form leaves nothing behind.
 *
 * The same contract as `pendingPlacements`: collected on the form, applied once the record exists.
 */
import type { ReferenceInput } from "../api/externalReferences";

const pending = new Map<string, ReferenceInput[]>();

const keyOf = (projectId: string, artefactType: string) => `${projectId}:${artefactType}`;

/** Records the references chosen on the open create form (an empty list removes the entry). */
export function setPendingReferences(projectId: string, artefactType: string, references: ReferenceInput[]): void {
  if (references.length === 0) pending.delete(keyOf(projectId, artefactType));
  else pending.set(keyOf(projectId, artefactType), references);
}

/** Returns the references chosen on the create form and forgets them, so a second create never reuses them. */
export function takePendingReferences(projectId: string, artefactType: string): ReferenceInput[] {
  const key = keyOf(projectId, artefactType);
  const references = pending.get(key) ?? [];
  pending.delete(key);
  return references;
}
