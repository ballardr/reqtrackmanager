/**
 * Module: modules/stakeholders/ProjectStakeholdersPage
 *
 * The project-scoped Stakeholder list route, mounted at
 * `/projects/:projectId/modules/stakeholders/stakeholders` (`module.ts`,
 * reached via the "Stakeholders" nav-rail entry). Lists the project's own
 * stakeholders *and* the organisation's live ones (Phase 0 resolution 2); new
 * stakeholders created here are project-scoped. The list/filter/create UI is
 * the shared `StakeholderListView`. Every row opens inside this project (an org
 * stakeholder too); `StakeholderDetailPage` makes an org stakeholder read-only
 * there and is where one is hidden from the project. "Show hidden" lists the
 * org stakeholders hidden from this project so they can be shown again.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../../api/client";
import type { OrgUser, Project } from "../../api/types";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectStakeholderApi } from "./api";
import { StakeholderListView } from "./StakeholderListView";
import type { EffectivePersonaType, Stakeholder } from "./types";
import { useStakeholderScheme } from "./useStakeholderScheme";

export function ProjectStakeholdersPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [stakeholders, setStakeholders] = useState<Stakeholder[] | null>(null);
  const [types, setTypes] = useState<EffectivePersonaType[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [includeHidden, setIncludeHidden] = useState(false);
  const scheme = useStakeholderScheme({ projectId: projectId ?? "" });

  const [refreshKey, setRefreshKey] = useState(0);
  const reload = () => setRefreshKey((k) => k + 1);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    Promise.all([
      projectStakeholderApi.list(projectId, { include_archived: includeArchived, include_hidden: includeHidden }),
      projectStakeholderApi.listTypes(projectId),
    ])
      .then(([list, typeList]) => {
        if (!active) return;
        setStakeholders(list);
        setTypes(typeList);
        setLoadError(null);
      })
      .catch((err) => {
        if (active) setLoadError(toErrorMessage(err, "The Stakeholders & Personas module isn't enabled for this project's organisation, or you don't have access to it."));
      });
    return () => {
      active = false;
    };
  }, [projectId, includeArchived, includeHidden, refreshKey]);

  useEffect(() => {
    if (!projectId) return;
    api
      .get<Project>(`/api/v1/projects/${projectId}`)
      .then((p) => api.get<OrgUser[]>(`/api/v1/orgs/${p.organization_id}/users`))
      .then(setOrgUsers)
      .catch(() => setOrgUsers([]));
  }, [projectId]);

  /** Shows a hidden stakeholder again: drops this project's own hide, then, if a
   * parent project still hides it, overrides that with an explicit "shown". */
  async function showHidden(stakeholder: Stakeholder) {
    if (!projectId) return;
    try {
      let updated = stakeholder;
      if (stakeholder.hidden_source === "project") updated = await projectStakeholderApi.clearVisibility(projectId, stakeholder.id);
      if (updated.project_hidden) await projectStakeholderApi.setVisibility(projectId, stakeholder.id, false);
      showToast(`${stakeholder.name} is shown in this project again.`);
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not show this Stakeholder."), "error");
    }
  }

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (stakeholders === null) return <Spinner />;

  return (
    <div className="container stack">
      <h1 style={{ margin: 0 }}>Stakeholders</h1>
      <StakeholderListView
        stakeholders={stakeholders}
        ariaLabel="Stakeholders"
        sectionKey="stakeholders.stakeholders.list"
        scopeLabel="project"
        emptyText="No Stakeholders recorded for this project yet."
        showScope
        typeOptions={types.filter((t) => t.is_enabled).map((t) => ({ value: t.id, label: t.name }))}
        scheme={scheme}
        orgUsers={orgUsers}
        loadHint={(influence, interest) => projectStakeholderApi.cadenceHint(projectId, influence, interest)}
        includeArchived={includeArchived}
        onIncludeArchivedChange={setIncludeArchived}
        includeHidden={includeHidden}
        onIncludeHiddenChange={setIncludeHidden}
        onShowHidden={showHidden}
        onOpen={(s) => navigate(`/projects/${projectId}/modules/stakeholders/stakeholders/${s.id}`)}
        onCreate={async (values) => {
          await projectStakeholderApi.create(projectId, values);
          showToast("Stakeholder created.");
          reload();
        }}
        onCreateFromUser={async (values) => {
          await projectStakeholderApi.createFromUser(projectId, values);
          showToast("Stakeholder created from user.");
          reload();
        }}
      />
    </div>
  );
}
