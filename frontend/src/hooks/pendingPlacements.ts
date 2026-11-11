/**
 * Module: hooks/pendingPlacements
 *
 * The places a create form has collected for a record that does not exist yet, handed from the form's
 * `ComponentField` to the create path's `useCommitTags` without every form's `onSave` signature growing a
 * parameter. Keyed by project and record type, because a create form is open for one record type at a time;
 * the field clears its entry when it unmounts, so a cancelled form leaves nothing behind.
 *
 * This is deliberately the same contract as tags (collected on the form, applied once the record exists): the
 * field and the commit step are the only two places that know about it.
 */
import type { PlacementPair } from "../api/placements";

const pending = new Map<string, PlacementPair[]>();

const keyOf = (projectId: string, artefactType: string) => `${projectId}:${artefactType}`;

/** Records the places chosen on the open create form (an empty list removes the entry). */
export function setPendingPlacements(projectId: string, artefactType: string, places: PlacementPair[]): void {
  if (places.length === 0) pending.delete(keyOf(projectId, artefactType));
  else pending.set(keyOf(projectId, artefactType), places);
}

/** Returns the places chosen on the create form and forgets them, so a second create never reuses them. */
export function takePendingPlacements(projectId: string, artefactType: string): PlacementPair[] {
  const key = keyOf(projectId, artefactType);
  const places = pending.get(key) ?? [];
  pending.delete(key);
  return places;
}
