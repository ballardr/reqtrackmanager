/**
 * Module: modules/orgResources
 *
 * Turns the `orgResourceSections` installed modules contribute into the sections Org Resources
 * (`pages/OrgResourcesPage.tsx`) shows, and answers where a section lives:
 * - `collectOrgResourceSections`: the sections of enabled modules (and enabled sub-components), minus any whose key
 *   would collide with another section or a reserved core group.
 * - `orgResourcesPath`: the address of the page, or of one section by its key.
 * - `findOrgResourceSectionPath`: the address of a section by key across every installed module, enablement
 *   ignored, so an earlier address (the Organisation Overview section it used to be) can be redirected.
 *
 * It reads only the generic section shape and the registry and names no module, so core never imports a module's
 * directory for Org Resources. A section is addressed `/orgs/:orgId/resources/:group/:section` (see
 * `adminMenu.ts`), the same grouping and redirect rules as the administration pages.
 */
import type { OrgModuleSubComponent } from "../api/types";
import { adminSectionPath } from "./adminMenu";
import { installedModules } from "./registry";
import type { OrgAdminSectionDef, TierAModuleDefinition } from "./types";

/** Group keys the Org Resources page itself declares; a module section may not use one. */
export const CORE_ORG_RESOURCE_GROUP_KEYS: readonly string[] = [];

/** The Org Resources address of an organisation, or of one section when its key is given (an ungrouped section's
 * own address; a grouped one is redirected to its full address by the page). */
export function orgResourcesPath(orgId: string, sectionKey?: string): string {
  const base = `/orgs/${orgId}/resources`;
  return sectionKey ? `${base}/${sectionKey}` : base;
}

/**
 * The full Org Resources address of the section with this key, found across every installed module.
 *
 * @param orgId The organisation the address is for.
 * @param sectionKey The section key (an earlier Overview address used it as its `:group` segment).
 * @returns The address, or `null` when no installed module declares the key.
 */
export function findOrgResourceSectionPath(orgId: string, sectionKey: string): string | null {
  for (const module of installedModules) {
    const section = (module.orgResourceSections ?? []).find((s) => s.key === sectionKey);
    if (section) return adminSectionPath(orgResourcesPath(orgId), section);
  }
  return null;
}

/**
 * The sections the caller is offered, in module order.
 *
 * A module that is off for the organisation contributes nothing; a section tied to a sub-component is left out once
 * that sub-component is known to be off (`subComponents` holds only what the caller could read). A section whose key
 * (or group key) is reserved, or already used by another section as a section or a group, is dropped with a console
 * error rather than shadowing the other, because two entries for one address would make one unreachable.
 *
 * @param modules The installed modules (injectable for tests).
 * @param enabledKeys Keys of the modules enabled for the organisation.
 * @param subComponents Sub-component state by module key, for the modules that were asked.
 * @param reservedKeys Group keys the page owns.
 */
export function collectOrgResourceSections(
  modules: TierAModuleDefinition[],
  enabledKeys: ReadonlySet<string>,
  subComponents: Record<string, OrgModuleSubComponent[] | undefined>,
  reservedKeys: readonly string[] = CORE_ORG_RESOURCE_GROUP_KEYS,
): OrgAdminSectionDef[] {
  const sectionKeys = new Set<string>();
  const ungroupedKeys = new Set<string>();
  const groupKeys = new Set<string>();
  const result: OrgAdminSectionDef[] = [];
  for (const module of modules) {
    if (!enabledKeys.has(module.key)) continue;
    for (const section of module.orgResourceSections ?? []) {
      const subs = subComponents[module.key];
      if (section.subComponent && subs && !subs.some((s) => s.subcomponent_key === section.subComponent && s.enabled)) continue;
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
