/**
 * Module: components/referenceDraft
 *
 * The values one external reference's fields edit (`ReferenceFields`) and their conversion to and from the API shapes,
 * kept apart from the components so those files export only components. The one draft behind both places a reference
 * is edited: the create form's `ReferenceField` rows and the record page's `ReferenceFormModal`.
 */
import type { ExternalReference, ExternalReferenceRole, ReferenceInput } from "../api/externalReferences";

/** One reference being edited; `role` is `""` for none. */
export interface ReferenceDraft {
  systemId: string;
  key: string;
  url: string;
  note: string;
  role: ExternalReferenceRole | "";
}

export const BLANK_REFERENCE: ReferenceDraft = { systemId: "", key: "", url: "", note: "", role: "" };

/** The draft of an existing reference. */
export function draftFromReference(reference: ExternalReference): ReferenceDraft {
  return {
    systemId: reference.system_id, key: reference.key, url: reference.url ?? "", note: reference.note, role: reference.role ?? "",
  };
}

/** Whether a draft can be saved: a system, and a key or a link. */
export function referenceIsComplete(draft: ReferenceDraft): boolean {
  return draft.systemId !== "" && (draft.key.trim() !== "" || draft.url.trim() !== "");
}

/** The API body for one draft (a blank link or role is sent as `null`). */
export function referenceInput(draft: ReferenceDraft): ReferenceInput {
  return {
    system_id: draft.systemId, key: draft.key.trim(), url: draft.url.trim() || null, note: draft.note.trim(),
    role: draft.role === "" ? null : draft.role,
  };
}

/** The complete drafts as API bodies (a half-filled row is left out, not an error). */
export function referenceInputs(drafts: ReferenceDraft[]): ReferenceInput[] {
  return drafts.filter(referenceIsComplete).map(referenceInput);
}
