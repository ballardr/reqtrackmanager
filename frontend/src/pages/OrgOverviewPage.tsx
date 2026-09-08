import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Organization, OrgModule, OrgOverviewStats } from "../api/types";
import { ResourceMenu, type ResourceMenuGroupDef } from "../components/ResourceMenu";
import { Spinner } from "../components/Spinner";
import { StatCard } from "../components/StatCard";
import { installedModules } from "../modules/registry";
import { formatFileSize } from "../utils/formatFileSize";

/**
 * "Organisation Overview" (compliance-module-plan.md Phase 19) — a new
 * top-level, always-visible nav-rail page (unlike Phase 18's "Compliance
 * Standards" tab, this one carries general-purpose org stats every org has
 * regardless of whether compliance applies, so it's shown unconditionally
 * to any org member, the same precedent as the always-shown Projects link;
 * see `docs/decisions.md`'s "Compliance module, human review follow-ups"
 * entry). Reached via `/org-overview` (`OrgListPage`'s single-org/multi-org
 * auto-redirect, reused rather than duplicated — see that component's own
 * docstring) or directly at `/orgs/:orgId/overview`.
 *
 * A stats header (project/requirement/member counts, total file storage —
 * `GET /orgs/{id}/overview-stats`) is always shown; a `ResourceMenu` of any
 * installed, currently-enabled module's own `orgOverviewSections` (e.g.
 * Compliance's dashboard/standards/outstanding view, relocated here from
 * `OrgAdminPage.tsx`'s `"compliance-overview"` group) is rendered below it
 * only when at least one module actually contributes one — this core page
 * never imports a specific module directly, the same "core doesn't
 * hardcode one module" boundary `Layout.tsx`/`OrgAdminPage.tsx` already
 * establish for `globalNavItems`/`orgAdminSections`.
 */
export function OrgOverviewPage() {
  const { orgId, group: groupParam } = useParams<{ orgId: string; group?: string }>();
  const [org, setOrg] = useState<Organization | null>(null);
  const [stats, setStats] = useState<OrgOverviewStats | null>(null);
  const [modules, setModules] = useState<OrgModule[]>([]);

  useEffect(() => {
    if (!orgId) return;
    api.get<Organization>(`/api/v1/orgs/${orgId}`).then(setOrg);
    api.get<OrgOverviewStats>(`/api/v1/orgs/${orgId}/overview-stats`).then(setStats);
    api.get<OrgModule[]>(`/api/v1/orgs/${orgId}/modules`).then(setModules);
  }, [orgId]);

  if (!orgId) return null;
  if (!org || !stats) return <Spinner />;

  // Same "filter installed modules to this org's actually-enabled set"
  // pattern `OrgAdminPage.tsx` already uses for `orgAdminSections` —
  // dropping a since-disabled module's contribution here too, not just at
  // `OrgAdminPage.tsx`'s own admin surface.
  const enabledModuleKeys = new Set(modules.filter((m) => m.enabled).map((m) => m.module_key));
  const sections = installedModules
    .filter((m) => enabledModuleKeys.has(m.key))
    .flatMap((m) => m.orgOverviewSections ?? []);

  const groups: ResourceMenuGroupDef<string>[] = sections.map((section) => ({
    key: section.key,
    label: section.label,
    href: `/orgs/${orgId}/overview/${section.key}`,
  }));
  const activeSection = sections.find((s) => s.key === groupParam) ?? sections[0];

  return (
    <div className="stack">
      <h1 style={{ margin: 0 }}>{org.name}</h1>

      <div className="row" style={{ gap: "1rem", flexWrap: "wrap" }}>
        <StatCard label="Projects" value={stats.project_count} />
        <StatCard label="Requirements" value={stats.requirement_count} />
        <StatCard label="Members" value={stats.member_count} />
        <StatCard label="File storage" value={formatFileSize(stats.total_file_size_bytes)} />
      </div>
      {!stats.is_full_org_total && (
        <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
          These figures are scoped to what you can see, not this organisation's full totals.
        </p>
      )}

      {activeSection && (
        <ResourceMenu ariaLabel="Organisation overview sections" groups={groups} active={activeSection.key}>
          {activeSection.render({ orgId })}
        </ResourceMenu>
      )}
    </div>
  );
}
