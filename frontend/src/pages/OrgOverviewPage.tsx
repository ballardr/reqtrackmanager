import { Fragment, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Organization, OrgModule, OrgOverviewStats } from "../api/types";
import { ResourceMenu, type ResourceMenuGroupDef } from "../components/ResourceMenu";
import { Spinner } from "../components/Spinner";
import { StatCard } from "../components/StatCard";
import { getInstalledModule, installedModules } from "../modules/registry";
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
 * `GET /orgs/{id}/overview-stats` — plus any installed, currently-enabled
 * module's own `orgOverviewTiles`, e.g. Compliance's overall-compliance-
 * percentage/standards-count/non-compliant-projects headline gauges, Phase
 * 25b) is always shown as one equal-size `.grid.grid-metrics` grid; a
 * `ResourceMenu` of any such module's own `orgOverviewSections` (e.g.
 * Compliance's Dashboard/Compliance-by-standard/Outstanding groups,
 * relocated here from `OrgAdminPage.tsx`'s `"compliance-overview"` group,
 * Phase 19, then split from one nested-`Tabs` group into three flat
 * top-level groups, Phase 25b) is rendered below it only when at least one
 * module actually contributes one — this core page never imports a
 * specific module directly, the same "core doesn't hardcode one module"
 * boundary `Layout.tsx`/`OrgAdminPage.tsx` already establish for
 * `globalNavItems`/`orgAdminSections`.
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

  // Memoized on `[modules, orgId]` rather than recomputed inline in the
  // render body — `tile.render({orgId})` builds a fresh React element each
  // call, and this page's own `org`/`stats` state each resolve
  // independently after mount, so an unmemoized version would hand each
  // contributed tile a new element identity (forcing React to unmount and
  // remount it, re-running its own effects/fetches) on every one of those
  // unrelated re-renders, not just when `modules` itself actually changes.
  const contributedTiles = useMemo(
    () =>
      orgId
        ? modules
            .filter((m) => m.enabled)
            .flatMap((entry) =>
              (getInstalledModule(entry.module_key)?.orgOverviewTiles ?? []).map((tile) => ({
                key: `${entry.module_key}:${tile.key}`,
                node: tile.render({ orgId }),
              }))
            )
        : [],
    [modules, orgId]
  );

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

      <div className="grid grid-metrics">
        <StatCard label="Projects" value={stats.project_count} />
        <StatCard label="Requirements" value={stats.requirement_count} />
        <StatCard label="Members" value={stats.member_count} />
        <StatCard label="File storage" value={formatFileSize(stats.total_file_size_bytes)} />
        {contributedTiles.map((t) => (
          <Fragment key={t.key}>{t.node}</Fragment>
        ))}
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
