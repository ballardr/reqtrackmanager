/**
 * Module: modules/orgResources
 *
 * Turns the `orgResourceSections` installed modules contribute into the sections Org Resources
 * (`pages/OrgResourcesPage.tsx`) shows, and answers where a section lives:
 * - `collectOrgResourceSections`: the sections of enabled modules (and enabled sub-components), minus any whose key
 *   would collide with another section or a reserved core group.
 * - `orgResourcesPath`: the address of the page, or of one section by its key.
 *
 * It reads only the generic section shape and the registry and names no module, so core never imports a module's
 * directory for Org Resources. A section is addressed `/orgs/:orgId/resources/:group/:section` (see
 * `adminMenu.ts`), the same grouping rules as the administration pages.
 */
import type { OrgAdminSectionDef, TierAModuleDefinition } from "./types";

/** Section keys the Org Resources page itself declares (the organisation's report resources and tag vocabulary); a
 * module section may not use one. Their Organisation Settings addresses (`/admin/reports`, `/admin/tags`) redirect. */
export const CORE_ORG_RESOURCE_GROUP_KEYS: readonly string[] = ["reports", "tags"];

/** The Org Resources address of an organisation, or of one section when its key is given (an ungrouped section's
 * own address; a grouped one is redirected to its full address by the page). */
export function orgResourcesPath(orgId: string, sectionKey?: string): string {
  const base = `/orgs/${orgId}/resources`;
  return sectionKey ? `${base}/${sectionKey}` : base;
}

/**
 * The sections the caller is offered, in module order.
 *
 * A module that is off for the organisation contributes nothing; a section tied to a sub-component is left out while
 * that sub-component is off. A section whose key
 * (or group key) is reserved, or already used by another section as a section or a group, is dropped with a console
 * error rather than shadowing the other, because two entries for one address would make one unreachable.
 *
 * @param modules The installed modules (injectable for tests).
 * @param enabledKeys Keys of the modules enabled for the organisation.
 * @param disabledSubComponents Keys of the sub-components that are off, by module key.
 * @param reservedKeys Group keys the page owns.
 */
export function collectOrgResourceSections(
  modules: TierAModuleDefinition[],
  enabledKeys: ReadonlySet<string>,
  disabledSubComponents: Readonly<Record<string, readonly string[] | undefined>>,
  reservedKeys: readonly string[] = CORE_ORG_RESOURCE_GROUP_KEYS,
): OrgAdminSectionDef[] {
  const sectionKeys = new Set<string>();
  const ungroupedKeys = new Set<string>();
  const groupKeys = new Set<string>();
  const result: OrgAdminSectionDef[] = [];
  for (const module of modules) {
    if (!enabledKeys.has(module.key)) continue;
    for (const section of module.orgResourceSections ?? []) {
      if (section.subComponent && disabledSubComponents[module.key]?.includes(section.subComponent)) continue;
      const top = section.group?.key ?? section.key;
      const clash =
        reservedKeys.includes(top) || sectionKeys.has(section.key) ||
        (section.group ? ungroupedKeys.has(top) : groupKeys.has(top));
      if (clash) {
        console.error(`Org Resources section "${section.key}" of module "${module.key}" collides with another entry; ignoring it.`);
        continue;
      }
      sectionKeys.add(section.key);
      if (section.group) groupKeys.add(top);
      else ungroupedKeys.add(top);
      result.push(section);
    }
  }
  return result;
}
