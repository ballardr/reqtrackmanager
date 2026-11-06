/**
 * Module: modules/adminMenu
 *
 * Turns the admin sections installed modules contribute (`orgAdminSections`, `projectAdminSections`) into
 * `ResourceMenu` entries and resolves an admin URL to a section:
 * - `buildAdminMenuEntries`: sections sharing a declared `group` become one expandable entry with sub-pages; a section
 *   with no group, or the only visible section of its group, is a single entry.
 * - `resolveAdminSection`: reads `/…/admin/:group/:section?` and finds the section it names, or the redirect that
 *   brings an earlier address to the current one.
 *
 * Shared by `OrgAdminPage` and `ProjectAdminPage` so both pages group, link and redirect identically. It reads only the
 * generic section shape and names no module. Menus have two levels at most; a section's group never nests.
 */
import type { ResourceMenuGroupDef } from "../components/ResourceMenu";
import type { AdminSectionGroup } from "./types";

/** The part of an admin section definition this module reads. */
export interface AdminSectionLike {
  key: string;
  label: string;
  group?: AdminSectionGroup;
}

/** The URL path of one section: `/<base>/<group>/<section>` for a grouped section, `/<base>/<section>` otherwise. */
export function adminSectionPath(basePath: string, section: AdminSectionLike): string {
  return section.group ? `${basePath}/${section.group.key}/${section.key}` : `${basePath}/${section.key}`;
}

/**
 * Builds the menu entries for module-contributed sections, in the order the modules declared them.
 *
 * Args:
 *   sections: The sections visible to the caller (already filtered by module and sub-component state).
 *   basePath: The admin page path without a trailing slash, for example `/orgs/<id>/admin`.
 *
 * Returns:
 *   One entry per ungrouped section, one entry per group with two or more visible sections (with `children`), and a
 *   plain entry for a group left with one visible section. A group sits where its first section was declared.
 */
export function buildAdminMenuEntries(sections: AdminSectionLike[], basePath: string): ResourceMenuGroupDef<string>[] {
  const entries: ResourceMenuGroupDef<string>[] = [];
  const grouped = new Map<string, AdminSectionLike[]>();
  const slots = new Map<string, number>();
  for (const section of sections) {
    if (!section.group) {
      entries.push({ key: section.key, label: section.label, href: adminSectionPath(basePath, section) });
      continue;
    }
    const members = grouped.get(section.group.key);
    if (members) {
      members.push(section);
    } else {
      grouped.set(section.group.key, [section]);
      slots.set(section.group.key, entries.length);
      // Reserve the group's position; it is filled in below once every member is known.
      entries.push({ key: section.group.key, label: section.group.label, href: "" });
    }
  }
  for (const [groupKey, members] of grouped) {
    const slot = slots.get(groupKey) as number;
    const children = members.map((m) => ({ key: m.key, label: m.label, href: adminSectionPath(basePath, m) }));
    entries[slot] =
      children.length === 1
        ? { key: children[0].key, label: children[0].label, href: children[0].href }
        : { key: groupKey, label: (members[0].group as AdminSectionGroup).label, href: children[0].href, children };
  }
  return entries;
}

/** The result of reading an admin URL against the visible module sections. */
export interface AdminSectionRoute<S extends AdminSectionLike> {
  /** The section the URL names, or `null` when it names none (a core group, or an unknown segment). */
  section: S | null;
  /** The address to replace this one with, when it is an earlier or partial form of a section's address. */
  redirectTo: string | null;
}

/**
 * Finds the module section an admin URL names.
 *
 * Accepted: `/<group>/<section>`; `/<section>` for an ungrouped section; `/<group>` (redirects to the group's first
 * visible section); and `/<section>` for a grouped section, the address used before groups existed (redirects to the
 * grouped address, so bookmarks keep working). A mismatched `:section` under a known group redirects to the group's
 * first section.
 *
 * Args:
 *   sections: The sections visible to the caller.
 *   basePath: The admin page path without a trailing slash.
 *   groupParam: The `:group` URL segment, if any.
 *   sectionParam: The `:section` URL segment, if any.
 *
 * Returns:
 *   The matched section and/or a redirect target; both `null` when the segments name no module section.
 */
export function resolveAdminSection<S extends AdminSectionLike>(
  sections: S[],
  basePath: string,
  groupParam: string | undefined,
  sectionParam: string | undefined,
): AdminSectionRoute<S> {
  const none = { section: null, redirectTo: null };
  if (!groupParam) return none;
  const inGroup = sections.filter((s) => s.group?.key === groupParam);
  if (inGroup.length > 0) {
    const named = inGroup.find((s) => s.key === sectionParam);
    return named ? { section: named, redirectTo: null } : { section: null, redirectTo: adminSectionPath(basePath, inGroup[0]) };
  }
  const bySectionKey = sections.find((s) => s.key === groupParam);
  if (!bySectionKey) return none;
  // An ungrouped section answers to its bare key only; a grouped one is redirected to its full address.
  return bySectionKey.group
    ? { section: null, redirectTo: adminSectionPath(basePath, bySectionKey) }
    : { section: bySectionKey, redirectTo: null };
}
