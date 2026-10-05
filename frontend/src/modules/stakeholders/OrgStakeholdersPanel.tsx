/**
 * Module: modules/stakeholders/OrgStakeholdersPanel
 *
 * An organisation's own org-scoped Stakeholders (Phase 0 resolution 2: one
 * live, shared record every project can see), rendered as an
 * `OrgOverviewPage` `ResourceMenu` group (`module.ts`'s `orgOverviewSections`).
 *
 * Placement mirrors `OrgPersonasPanel` (Decided by: Agent): an org stakeholder
 * is org-level content its owners work with day to day, not a configuration
 * table — the Stakeholder *types* and scoring levels are the configuration and
 * live on `orgAdminSections`. The list/filter/create UI is the shared
 * `StakeholderListView`.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../../api/client";
import type { OrgUser } from "../../api/types";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgStakeholderApi, orgStakeholderTypeApi } from "./api";
import { StakeholderListView } from "./StakeholderListView";
import type { PersonaTypeDefinition, Stakeholder } from "./types";
import { useStakeholderScheme } from "./useStakeholderScheme";

export function OrgStakeholdersPanel({ orgId }: { orgId: string }) {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [stakeholders, setStakeholders] = useState<Stakeholder[] | null>(null);
  const [types, setTypes] = useState<PersonaTypeDefinition[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  const scheme = useStakeholderScheme({ orgId });

  const [refreshKey, setRefreshKey] = useState(0);
  const reload = () => setRefreshKey((k) => k + 1);

  useEffect(() => {
    let active = true;
    Promise.all([orgStakeholderApi.list(orgId, { include_archived: includeArchived }), orgStakeholderTypeApi.list(orgId)])
      .then(([list, typeList]) => {
        if (!active) return;
        setStakeholders(list);
        setTypes(typeList);
        setLoadError(null);
      })
      .catch((err) => {
        if (active) setLoadError(toErrorMessage(err, "The Stakeholders & Personas module isn't enabled for this organisation, or you don't have access to it."));
      });
    return () => {
      active = false;
    };
  }, [orgId, includeArchived, refreshKey]);

  useEffect(() => {
    api.get<OrgUser[]>(`/api/v1/orgs/${orgId}/users`).then(setOrgUsers).catch(() => setOrgUsers([]));
  }, [orgId]);

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (stakeholders === null) return <Spinner />;

  return (
    <StakeholderListView
      stakeholders={stakeholders}
      ariaLabel="Organisation Stakeholders"
      sectionKey="stakeholders.orgStakeholders.list"
      scopeLabel="organisation"
      emptyText="No organisation-scoped Stakeholders recorded yet."
      showScope={false}
      typeOptions={types.filter((t) => t.is_active).map((t) => ({ value: t.id, label: t.name }))}
      scheme={scheme}
      orgUsers={orgUsers}
      loadHint={(influence, interest) => orgStakeholderApi.cadenceHint(orgId, influence, interest)}
      includeArchived={includeArchived}
      onIncludeArchivedChange={setIncludeArchived}
      onOpen={(s) => navigate(`/orgs/${orgId}/modules/stakeholders/stakeholders/${s.id}`)}
      onCreate={async (values) => {
        await orgStakeholderApi.create(orgId, values);
        showToast("Stakeholder created.");
        reload();
      }}
      onCreateFromUser={async (values) => {
        await orgStakeholderApi.createFromUser(orgId, values);
        showToast("Stakeholder created from user.");
        reload();
      }}
    />
  );
}
