/**
 * Module: components/ProjectTagsPanel
 *
 * The Tags section of Project Admin: `TagAdminPanel` bound to one project's own vocabulary.
 */
import { useMemo } from "react";

import { projectTagAdminApi } from "../api/tags";
import { TagAdminPanel } from "./TagAdminPanel";

/** @param projectId The project whose tags are administered. */
export function ProjectTagsPanel({ projectId }: { projectId: string }) {
  const api = useMemo(() => projectTagAdminApi(projectId), [projectId]);
  return <TagAdminPanel api={api} scope="project" />;
}
