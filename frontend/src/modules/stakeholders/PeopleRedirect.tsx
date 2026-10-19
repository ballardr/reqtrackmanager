/**
 * Module: modules/stakeholders/PeopleRedirect
 *
 * Sends the old per-type list routes (`.../personas`, `.../stakeholders`, `.../needs`) to the People page with
 * that kind selected, so bookmarks and links from before the lists were merged keep working. Detail routes
 * (`.../personas/:id`) are unchanged and do not use this.
 */
import { Navigate, useParams } from "react-router-dom";

import type { PeopleKind } from "./peopleRows";

/**
 * @param kind The kind the old route listed; becomes the People page's `?kind=`.
 */
export function PeopleRedirect({ kind }: { kind: PeopleKind }) {
  const { projectId } = useParams<{ projectId: string }>();
  if (!projectId) return null;
  return <Navigate to={`/projects/${projectId}/modules/stakeholders/people?kind=${kind}`} replace />;
}
