/**
 * Module: modules/product_feedback/referenceDraft
 *
 * The values an external reference's fields edit (`ReferenceFields`), and their conversion to and from the API
 * shapes, kept apart from the components so those files export only components.
 */
import type { ExternalRef, ExternalRefInput, ExternalRefRole } from "./types";

/** One reference being edited. */
export interface ReferenceDraft {
  systemId: string;
  key: string;
  url: string;
  role: ExternalRefRole;
}

export const BLANK_REFERENCE: ReferenceDraft = { systemId: "", key: "", url: "", role: "delivery" };

/** The draft of an existing reference. */
export function draftFromReference(ref: ExternalRef): ReferenceDraft {
  return { systemId: ref.system_id, key: ref.key, url: ref.url ?? "", role: ref.role };
}

/** Whether a draft can be saved: a system, and a key or a link. */
export function referenceIsComplete(draft: ReferenceDraft): boolean {
  return draft.systemId !== "" && (draft.key.trim() !== "" || draft.url.trim() !== "");
}

/** The API body for one draft. */
export function referenceInput(draft: ReferenceDraft): ExternalRefInput {
  return { system_id: draft.systemId, key: draft.key.trim(), url: draft.url.trim() || null, role: draft.role };
}

/** The create payload's `references`: the complete drafts only (a half-filled row is left out, not an error). */
export function referencesPayload(drafts: ReferenceDraft[]): ExternalRefInput[] {
  return drafts.filter(referenceIsComplete).map(referenceInput);
}

/** True for an absolute http(s) URL: the only kind a reference is rendered as a clickable link. */
export function isWebUrl(value: string): boolean {
  try {
    return ["http:", "https:"].includes(new URL(value).protocol);
  } catch {
    return false;
  }
}
