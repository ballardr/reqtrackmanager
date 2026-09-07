/**
 * Module: modules/compliance/ComplianceAdminPanel
 *
 * The Compliance Module's org-level, Compliance-Manager-facing management
 * UI (docs/compliance-module-plan.md Phase 12; requirements doc §2-§6,
 * §19) — the org's catalogue of compliance standards, their versions, the
 * requirement tree within each version, required actions, and the two
 * extensible vocabularies (required-action types, cross-standard mapping
 * relationship types). Explicitly NOT the project-level assignment/
 * assessment UI (Phase 13) or the org-wide dashboard (Phase 14).
 *
 * Built as a Tier A installed module (docs/compliance-module-plan.md Phase
 * 3) — every component here is a direct, build-time-compiled import using
 * this app's real shared components (`DirectoryTable`, `FilterPanel`,
 * `Modal`, `SidePanel`, `DefinitionList`, `Tabs`, `ConfirmDialog`,
 * `useToast()`), not a lookalike.
 *
 * Mounting mechanism (a deliberate deviation from Phase 3's own routing
 * plumbing — see below for the up-to-date mechanism, and
 * docs/compliance-module-plan.md's Phase 12 notes for why Phase 12
 * originally had to hardcode it): Phase 3's `installedModules`/
 * `buildModuleRoutes` registry is project-scoped end to end
 * (`useProjectEnabledModules` fetches `GET /projects/{id}/enabled-modules`,
 * and both the nav rail and route splicing key off a `projectId` parsed
 * from the current URL) — it has no org-level equivalent, and Compliance's
 * org-level catalogue naturally has no owning project at all.
 *
 * **Updated by the module system follow-up (2026-09-07, see
 * `docs/decisions.md`'s "Module system follow-up: dynamic org-admin panel
 * registration" entry): this panel is no longer mounted by a hardcoded
 * `OrgAdminPage.tsx` render block.** `./module.ts` declares it as one of
 * this module's `orgAdminSections` (`modules/types.ts`), and
 * `OrgAdminPage.tsx` renders whichever section matches the active
 * `ResourceMenu` group generically — its own `activeGroup === "compliance"`
 * check (and the matching static top-of-file import of this component) is
 * gone. `OrgAdminPage.tsx` still owns the actual `<ResourceMenu>` — the
 * same page every org member (not just admins) already reaches via `/orgs`
 * regardless of role, with its established pattern for a section not every
 * viewer can use (fetch, catch a 403/404, degrade gracefully) that this
 * panel's own children still follow via `require_org_module_enabled`'s
 * 404-on-disabled response — only *which module contributes which group*
 * is no longer hand-wired there.
 *
 * This component still satisfies Tier A's actual definition — "installed at
 * build time, direct component imports, full consistency" — only the
 * *project-scoped routing/nav-discovery* half of Phase 3's mechanism
 * (which has no org-scoped analogue) doesn't apply here; `orgAdminSections`
 * is that analogue now.
 */
import { useEffect, useState } from "react";

import { Tabs, tabPanelProps } from "../../components/Tabs";
import { toErrorMessage } from "../../context/ToastContext";
import { ActionTypesPanel } from "./ActionTypesPanel";
import * as complianceApi from "./api";
import { MappingTypesPanel } from "./MappingTypesPanel";
import { StandardsPanel } from "./StandardsPanel";
import type { ComplianceActionType } from "./types";

type ComplianceTabKey = "standards" | "actionTypes" | "mappingTypes";

export function ComplianceAdminPanel({ orgId }: { orgId: string }) {
  const [tab, setTab] = useState<ComplianceTabKey>("standards");
  const [actionTypes, setActionTypes] = useState<ComplianceActionType[] | null>(null);
  const [moduleError, setModuleError] = useState<string | null>(null);

  async function reloadActionTypes() {
    setActionTypes(await complianceApi.listActionTypes(orgId));
  }

  useEffect(() => {
    setActionTypes(null);
    setModuleError(null);
    reloadActionTypes().catch((err) =>
      setModuleError(
        toErrorMessage(err, "The Compliance module isn't enabled for this organisation, or you don't have access to it.")
      )
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  if (moduleError) {
    return <p className="text-muted">{moduleError}</p>;
  }
  if (actionTypes === null) {
    return <p>Loading…</p>;
  }

  return (
    <div className="stack">
      <Tabs<ComplianceTabKey>
        idPrefix="compliance-admin"
        active={tab}
        onChange={setTab}
        tabs={[
          { key: "standards", label: "Standards" },
          { key: "actionTypes", label: "Action types" },
          { key: "mappingTypes", label: "Mapping types" },
        ]}
      />
      {tab === "standards" && (
        <div {...tabPanelProps("compliance-admin", "standards")}>
          <StandardsPanel orgId={orgId} actionTypes={actionTypes} />
        </div>
      )}
      {tab === "actionTypes" && (
        <div {...tabPanelProps("compliance-admin", "actionTypes")}>
          <ActionTypesPanel orgId={orgId} items={actionTypes} onReload={reloadActionTypes} />
        </div>
      )}
      {tab === "mappingTypes" && (
        <div {...tabPanelProps("compliance-admin", "mappingTypes")}>
          <MappingTypesPanel orgId={orgId} />
        </div>
      )}
    </div>
  );
}
