/**
 * Module: utils/entitySwitcherLoaders
 *
 * Shared `EntitySwitcher` (docs/compliance-module-plan.md Phase 28) loaders
 * for the two core entity types a page can switch between — organisations
 * and projects. Each loader hits the same `?mine=true`/`?archived=false`
 * list endpoint every list page for that entity type already calls
 * (`OrgListPage.tsx`, `ProjectListPage.tsx`'s unfiltered project fetch),
 * and points every result at a specific target page for that entity (its
 * Overview vs. its Admin page) — kept here once rather than duplicated
 * per call site, since `OrgOverviewPage.tsx`, `OrgAdminPage.tsx`,
 * `ProjectOverviewPage.tsx` and `ProjectAdminPage.tsx` all need the
 * identical fetch/filter with only the target path differing.
 *
 * The compliance module's own standard-switcher loader is *not* here —
 * it lives in `modules/compliance/api.ts` alongside the rest of that
 * module's requests, since a core file (this one) must never import from
 * a module's own directory (`CLAUDE.md`'s "Modular Feature System
 * Boundary").
 */
import { api } from "../api/client";
import type { Organization, ProjectListItem } from "../api/types";
import type { EntitySwitcherOption } from "../components/EntitySwitcher";

export async function loadOrgSwitcherOptions(target: "overview" | "admin"): Promise<EntitySwitcherOption[]> {
  const orgs = await api.get<Organization[]>("/api/v1/orgs?mine=true");
  return orgs.filter((o) => o.is_active).map((o) => ({ id: o.id, label: o.name, href: `/orgs/${o.id}/${target}` }));
}

export async function loadProjectSwitcherOptions(target: "overview" | "admin"): Promise<EntitySwitcherOption[]> {
  const projects = await api.get<ProjectListItem[]>("/api/v1/projects?archived=false");
  return projects.map((p) => ({
    id: p.id,
    label: p.name,
    href: target === "overview" ? `/projects/${p.id}` : `/projects/${p.id}/admin`,
  }));
}
