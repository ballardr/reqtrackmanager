/**
 * Module: components/OrgTagsPanel
 *
 * The Tags section of Org Admin: `TagAdminPanel` bound to the organisation's own vocabulary, which
 * the organisation's own records (personas, stakeholders, strategies and so on) draw their tags from.
 */
import { useMemo } from "react";

import { orgTagAdminApi } from "../api/tags";
import { TagAdminPanel } from "./TagAdminPanel";

/** @param organizationId The organisation whose tags are administered. */
export function OrgTagsPanel({ organizationId }: { organizationId: string }) {
  const api = useMemo(() => orgTagAdminApi(organizationId), [organizationId]);
  return <TagAdminPanel api={api} scope="organisation" />;
}
