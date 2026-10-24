/**
 * Module: hooks/useOpenOnly
 *
 * The one rule for a record list that opens on its open items only (Pain
 * Points, Open Questions, Risks, Decisions): the "Open only" filter starts
 * ticked, stays visible, and is switched off by the link instead of by the
 * user hunting for it.
 *
 * Responsibilities:
 * - `opensOnOpenOnly`: decide, from the URL the page opened with, whether the
 *   filter starts ticked. A link that says `open=0`, or that names a slice the
 *   default would hide (a valid `status`, a type's own extra slice), starts
 *   unticked, so a link never lands on an empty list. `open=1` keeps it on.
 * - `useOpenOnly`: hold that state for the page, in the URL (`open=1|0`, always written) with the list's other
 *   filters, so the list comes back as it was left. The starting value is worked out once from the link the page
 *   opened with; it is not re-derived when the person later picks a status.
 *
 * What counts as "open" stays with each type (a `*_OPEN_STATUSES` list beside
 * its status labels); this module knows nothing about any one type, so a
 * module's list uses it without a core edit.
 */
import { useState } from "react";

import { useUrlFlag, type UrlSetter } from "./useUrlFilter";

/**
 * Whether a list starts on open items only.
 *
 * @param initial The URL's search parameters when the page opened.
 * @param validStatuses The statuses the page recognises; a `status` outside them is ignored,
 *   as it is for the status filter itself.
 * @param namesOtherSlice True when the link asks for a slice the type adds to `status`
 *   (for example "blockers only"), which the default would otherwise hide.
 * @returns False for `open=0`, or when the link names a status or other slice; true otherwise.
 */
export function opensOnOpenOnly(
  initial: URLSearchParams,
  validStatuses: readonly string[],
  namesOtherSlice = false,
): boolean {
  const open = initial.get("open");
  if (open === "1") return true;
  if (open === "0") return false;
  return !(validStatuses.includes(initial.get("status") ?? "") || namesOtherSlice);
}

/**
 * State for a list's "Open only" filter, seeded by `opensOnOpenOnly`.
 *
 * @param initial The URL's search parameters when the page opened.
 * @param validStatuses The statuses the page recognises.
 * @param namesOtherSlice True when the link names a slice beyond `status`.
 * @returns The current value and its setter, as `useState` does.
 */
export function useOpenOnly(
  initial: URLSearchParams,
  validStatuses: readonly string[],
  namesOtherSlice = false,
): [boolean, UrlSetter<boolean>] {
  const [startsOpen] = useState(() => opensOnOpenOnly(initial, validStatuses, namesOtherSlice));
  return useUrlFlag("open", startsOpen, { explicit: true });
}
