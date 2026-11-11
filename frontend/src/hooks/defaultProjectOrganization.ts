/**
 * Module: hooks/defaultProjectOrganization
 *
 * The person's default organisation for new projects: the one key in `ui_preferences` that holds it
 * (set on the Preferences page) and the rule that turns it into the organisation the New project
 * dialog starts on. The stored value is only an organisation id, so it is re-validated against the
 * organisations offered to the person on every read; a stale value (organisation disabled, left or
 * renamed away) degrades to the first organisation, never to a dead option.
 */
import type { Organization } from "../api/types";

/** The `ui_preferences` key holding the default organisation id; an empty string means "none". */
export const DEFAULT_NEW_PROJECT_ORG_PREFERENCE = "default_new_project_organization_id";

/**
 * Chooses the organisation the New project dialog starts on.
 *
 * @param orgs The active organisations the person can create a project in.
 * @param storedId The stored preference (any JSON value: the bag is open-ended).
 * @returns The stored organisation's id when it is offered, else the first organisation's id, else "".
 */
export function resolveNewProjectOrgId(orgs: Pick<Organization, "id">[], storedId: unknown): string {
  if (typeof storedId === "string" && storedId && orgs.some((o) => o.id === storedId)) return storedId;
  return orgs[0]?.id ?? "";
}
