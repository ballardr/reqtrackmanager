/**
 * Module: modules/compliance/ComplianceSettingsPage
 *
 * Org-level compliance settings at `/standards/settings/:orgId`
 * (docs/compliance-module-plan.md Phase 18) — the two extensible
 * vocabularies (`ActionTypesPanel`, `MappingTypesPanel`) that used to be
 * tabs inside `ComplianceAdminPanel.tsx` (now deleted, fully superseded),
 * re-hosted as their own routed page.
 *
 * Internal navigation between the two groups uses `ResourceMenu`
 * (`frontend/src/components/ResourceMenu.tsx`) — this codebase's
 * established "one page, persistent side menu of a handful of named
 * sections" pattern, already used by `ProjectAdminPage.tsx`/
 * `OrgAdminPage.tsx`/`ServerManagementPage.tsx` — not `Tabs` and not a
 * nav-rail section: a nav-rail section (`Layout.tsx`'s "Standard" section)
 * is reserved for an actual project-like *entity* (a single Standard), not
 * a fixed pair of org-wide settings screens. See docs/ux-style-guide.md's
 * new "Pattern: project-like drill-down entities" section for the full
 * reasoning behind this split.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../../api/client";
import type { Organization } from "../../api/types";
import type { ResourceMenuGroupDef } from "../../components/ResourceMenu";
import { ResourceMenu } from "../../components/ResourceMenu";
import { Spinner } from "../../components/Spinner";
import { ActionTypesPanel } from "./ActionTypesPanel";
import * as complianceApi from "./api";
import { MappingTypesPanel } from "./MappingTypesPanel";
import type { ComplianceActionType } from "./types";

type ComplianceSettingsGroupKey = "actionTypes" | "mappingTypes";

export function ComplianceSettingsPage() {
  const { orgId, group: groupParam } = useParams<{ orgId: string; group?: string }>();
  const [org, setOrg] = useState<Organization | null>(null);
  const [actionTypes, setActionTypes] = useState<ComplianceActionType[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  async function reloadActionTypes() {
    if (!orgId) return;
    setActionTypes(await complianceApi.listActionTypes(orgId));
  }

  useEffect(() => {
    if (!orgId) return;
    setActionTypes(null);
    setLoadError(null);
    api.get<Organization>(`/api/v1/orgs/${orgId}`).then(setOrg);
    reloadActionTypes().catch(() =>
      setLoadError("The Compliance module isn't enabled for this organisation, or you don't have access to it.")
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  const activeGroup: ComplianceSettingsGroupKey = groupParam === "mappingTypes" ? "mappingTypes" : "actionTypes";
  const groups: ResourceMenuGroupDef<ComplianceSettingsGroupKey>[] = [
    { key: "actionTypes", label: "Action types", href: `/standards/settings/${orgId}/actionTypes` },
    { key: "mappingTypes", label: "Mapping types", href: `/standards/settings/${orgId}/mappingTypes` },
  ];

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (!orgId || actionTypes === null) return <Spinner />;

  return (
    <ResourceMenu
      title={org ? `${org.name} — Compliance settings` : "Compliance settings"}
      ariaLabel="Compliance settings sections"
      groups={groups}
      active={activeGroup}
    >
      {activeGroup === "actionTypes" && (
        <ActionTypesPanel orgId={orgId} items={actionTypes} onReload={reloadActionTypes} />
      )}
      {activeGroup === "mappingTypes" && <MappingTypesPanel orgId={orgId} />}
    </ResourceMenu>
  );
}
