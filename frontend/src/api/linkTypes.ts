/**
 * Module: api/linkTypes
 *
 * Loads the link types a project offers in its pickers. A project's types are
 * not just the organisation's: its own and its ancestors' local types join
 * them, and what a project (or an ancestor) hid is left out, so every picker
 * asks the project rather than the organisation.
 */
import { api } from "./client";
import { offeredLinkTypes, type LinkTypeDefinition, type ProjectLinkType, type ProjectLinkTypes } from "./types";

/**
 * Every link type the project can reach (hidden and shadowed ones included), for
 * showing the name of a type a stored link or change request already uses.
 *
 * @param projectId The project.
 * @returns The types in precedence order (organisation-wide first).
 */
export async function loadReachableLinkTypes(projectId: string): Promise<ProjectLinkType[]> {
  return (await api.get<ProjectLinkTypes>(`/api/v1/projects/${projectId}/link-types`)).items;
}

/**
 * The link types a picker should offer for a new link in the project: not
 * hidden, not shadowed by a same-named type, and not a dedicated type.
 *
 * @param projectId The project.
 * @returns Types usable for a new link, as plain definitions.
 */
export async function loadOfferedLinkTypes(projectId: string): Promise<LinkTypeDefinition[]> {
  return offeredLinkTypes(await loadReachableLinkTypes(projectId)).filter((t) => !t.dedicated_endpoint);
}
