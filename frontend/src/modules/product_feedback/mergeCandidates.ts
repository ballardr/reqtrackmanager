/**
 * Module: modules/product_feedback/mergeCandidates
 *
 * Which requests a request may be merged into, kept apart from the dialog so that file exports only a component.
 */
import { REQUEST_OPEN_STATUSES, type EnhancementRequest } from "./types";

/** The requests `request` may be merged into: the other open ones, as the server accepts. */
export function mergeCandidates(request: EnhancementRequest, all: EnhancementRequest[]): EnhancementRequest[] {
  return all.filter((r) => r.id !== request.id && !r.is_archived && REQUEST_OPEN_STATUSES.includes(r.status));
}
