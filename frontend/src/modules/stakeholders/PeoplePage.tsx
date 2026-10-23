/**
 * Module: modules/stakeholders/PeoplePage
 *
 * The project's one page for Personas, Stakeholders and Stakeholder groups, mounted at
 * `/projects/:projectId/modules/stakeholders/people` (`module.ts`, the "People" nav entry). The old
 * per-type list routes redirect here with the matching `?kind=`. Stakeholder Needs are not people: they
 * have their own tab beside this one (`NeedsPage`, `PeopleTabs`), and `?kind=need` redirects there.
 *
 * - **Kinds:** chips (each with the kind's icon) choose which kinds are listed (default: every kind the
 *   project has switched on, so a kind whose sub-component is off is simply absent). Several kinds share
 *   the combined `PeopleListView`; exactly one shows that kind's own list with its own columns and filters
 *   (`PersonaListView`, `StakeholderListView`, or the group manager). The choice lives in the URL.
 * - **New:** one menu creates any kind. The create forms are the page's, so each list is shown without
 *   its own New button; "Save and activate" sits beside Save in them (activation has the same gate as
 *   creation, so it never bypasses an approval).
 * - Detail pages are unchanged: a row opens its own record, an org-owned one inside this project.
 */
import { useMemo, useRef, useState } from "react";
import { Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../../api/client";
import type { OrgUser, Project } from "../../api/types";
import { MenuButton } from "../../components/MenuButton";
import { Spinner } from "../../components/Spinner";
import { ToggleChips } from "../../components/ToggleChips";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
import { rowProjectId } from "../../api/projectScope";
import { useProjectScope } from "../../hooks/useProjectScope";
import { useTagFilter } from "../../hooks/useTagFilter";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useProjectEnabledModules } from "../../hooks/useProjectEnabledModules";
import { projectPersonaApi, projectStakeholderApi, projectStakeholderGroupApi } from "./api";
import { createStakeholderWithGroups } from "./createStakeholder";
import { PeopleKindIcon } from "./PeopleKindIcon";
import { PeopleListView } from "./PeopleListView";
import { PeopleTabs } from "./PeopleTabs";
import { peoplePanelProps } from "./peopleTabState";
import {
  PEOPLE_KIND_LABEL, PEOPLE_KIND_PLURAL_LABEL, enabledKinds, groupRow, kindQuery, namesNeedKind, needsEnabled, personaRow,
  selectedKinds, stakeholderRow, type PeopleKind, type PeopleRow,
} from "./peopleRows";
import { PersonaFormModal } from "./PersonaFormModal";
import { PersonaListView } from "./PersonaListView";
import { StakeholderFormModal } from "./StakeholderFormModal";
import { StakeholderFromUserModal } from "./StakeholderFromUserModal";
import { StakeholderGroupFormModal } from "./StakeholderGroupFormModal";
import { StakeholderGroupsPanel } from "./StakeholderGroupsPanel";
import { StakeholderListView } from "./StakeholderListView";
import type {
  EffectivePersonaType, Persona, PersonaFieldValues, Stakeholder, StakeholderFieldValues,
  StakeholderGroup, StakeholderGroupFieldValues,
} from "./types";
import { useStakeholderScheme } from "./useStakeholderScheme";
import { showRecordInProject } from "./visibility";

const MODULE_KEY = "stakeholders";
const NOT_AVAILABLE =
  "The Stakeholders & Personas module isn't enabled for this project's organisation, or you don't have access to it.";

/** Which create form is open: a kind, or the stakeholder-from-user variant. */
type Creating = PeopleKind | "stakeholder_from_user" | null;

export function PeoplePage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { showToast } = useToast();
  const commitPersonaLinks = useCommitQuickLinks(projectId ?? "", "persona");
  const commitStakeholderLinks = useCommitQuickLinks(projectId ?? "", "stakeholder");
  const commitPersonaTags = useCommitTags(projectId ?? "", "persona");
  const commitStakeholderTags = useCommitTags(projectId ?? "", "stakeholder");
  const { modules, loaded } = useProjectEnabledModules(projectId ?? null);
  const disabled = modules.find((m) => m.module_key === MODULE_KEY)?.disabled_sub_components;
  const enabled = useMemo(() => enabledKinds(disabled ?? []), [disabled]);
  const hasNeeds = needsEnabled(disabled ?? []);
  const selected = selectedKinds(params.get("kind"), enabled);
  const only = selected.length === 1 ? selected[0] : null;

  const [personas, setPersonas] = useState<Persona[]>([]);
  const [stakeholders, setStakeholders] = useState<Stakeholder[]>([]);
  const [groups, setGroups] = useState<StakeholderGroup[]>([]);
  const [personaTypes, setPersonaTypes] = useState<EffectivePersonaType[]>([]);
  const [stakeholderTypes, setStakeholderTypes] = useState<EffectivePersonaType[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [data, setData] = useState<"loading" | "ready">("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [includeHidden, setIncludeHidden] = useState(false);
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);
  const tagFilterProp = { projectId: projectId ?? "", filter: tagFilter };
  const [creating, setCreating] = useState<Creating>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const scheme = useStakeholderScheme({ projectId: projectId ?? "" });

  const [refreshKey, setRefreshKey] = useState(0);
  const reload = () => setRefreshKey((k) => k + 1);

  /** Counts loads so a slow, superseded response never replaces a newer one. */
  const loadSeq = useRef(0);
  const enabledKey = enabled.join(",");

  useLoadOnChange(
    () => {
      if (!projectId || !loaded || enabled.length === 0) return;
      const mine = ++loadSeq.current;
      const on = (k: PeopleKind) => enabled.includes(k);
      Promise.all([
        on("persona") ? projectPersonaApi.list(projectId, { include_archived: includeArchived, include_hidden: includeHidden, tags: tagFilter.tags, tag_mode: tagFilter.mode, project_scope: projectScope.scope }) : [],
        on("persona") ? projectPersonaApi.listTypes(projectId) : [],
        on("stakeholder") ? projectStakeholderApi.list(projectId, { include_archived: includeArchived, include_hidden: includeHidden, tags: tagFilter.tags, tag_mode: tagFilter.mode, project_scope: projectScope.scope }) : [],
        on("stakeholder") ? projectStakeholderApi.listTypes(projectId) : [],
        on("group") ? projectStakeholderGroupApi.list(projectId, { tags: tagFilter.tags, tag_mode: tagFilter.mode, project_scope: projectScope.scope }).catch(() => [] as StakeholderGroup[]) : [],
      ])
        .then(([p, pt, s, st, g]) => {
          if (mine !== loadSeq.current) return;
          setPersonas(p as Persona[]);
          setPersonaTypes(pt as EffectivePersonaType[]);
          setStakeholders(s as Stakeholder[]);
          setStakeholderTypes(st as EffectivePersonaType[]);
          setGroups(g as StakeholderGroup[]);
          setLoadError(null);
          setData("ready");
        })
        .catch((err) => {
          if (mine === loadSeq.current) setLoadError(toErrorMessage(err, NOT_AVAILABLE));
        });
    },
    [projectId, loaded, enabledKey, includeArchived, includeHidden, refreshKey, tagFilter.query, projectScope.scope],
  );

  useLoadOnChange(
    () => {
      if (!projectId || !enabled.includes("stakeholder")) return;
      api
        .get<Project>(`/api/v1/projects/${projectId}`)
        .then((p) => api.get<OrgUser[]>(`/api/v1/orgs/${p.organization_id}/users`))
        .then(setOrgUsers)
        .catch(() => setOrgUsers([]));
    },
    [projectId, enabledKey],
  );

  if (!projectId) return null;
  // The retired Need kind and a project with only Needs on both land on the Needs tab.
  if (namesNeedKind(params.get("kind")) && loaded && hasNeeds) {
    return <Navigate to={`/projects/${projectId}/modules/stakeholders/needs`} replace />;
  }
  if (loaded && enabled.length === 0 && hasNeeds) {
    return <Navigate to={`/projects/${projectId}/modules/stakeholders/needs`} replace />;
  }
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (!loaded || (enabled.length > 0 && data === "loading")) return <Spinner />;
  if (enabled.length === 0) return <p className="text-muted">{NOT_AVAILABLE}</p>;

  const typeOptions = (types: EffectivePersonaType[]) => types.filter((t) => t.is_enabled).map((t) => ({ value: t.id, label: t.name }));

  function setKinds(next: PeopleKind[]) {
    const query = kindQuery(next, enabled);
    // Keep the list's other parameters (search, filters, tags): they are part of the list's state.
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (query) next.set("kind", query);
      else next.delete("kind");
      return next;
    }, { replace: true });
  }

  function toggleKind(kind: PeopleKind) {
    const next = selected.includes(kind) ? selected.filter((k) => k !== kind) : enabled.filter((k) => k === kind || selected.includes(k));
    if (next.length > 0) setKinds(next);
  }

  // Group pickers and filters offer this project's own groups, not those of related projects in a widened list.
  const ownGroups = groups.filter((g) => !g.from_project_id);

  const rows: PeopleRow[] = [
    ...(selected.includes("persona") ? personas.map(personaRow) : []),
    ...(selected.includes("stakeholder") ? stakeholders.map(stakeholderRow) : []),
    ...(selected.includes("group") ? groups.map(groupRow) : []),
  ];

  function openRow(row: PeopleRow) {
    // A row of a related project opens in that project.
    const rowBase = `/projects/${rowProjectId(row, projectId ?? "")}/modules/stakeholders`;
    const path: Record<PeopleKind, string> = {
      persona: `${rowBase}/personas/${row.id}`,
      stakeholder: `${rowBase}/stakeholders/${row.id}`,
      group: `${rowBase}/groups?group=${row.id}`,
    };
    navigate(path[row.kind]);
  }

  async function showHidden(record: Persona | Stakeholder, kind: "persona" | "stakeholder") {
    const noun = PEOPLE_KIND_LABEL[kind];
    try {
      await showRecordInProject(kind === "persona" ? projectPersonaApi : projectStakeholderApi, projectId!, record);
      showToast(`${record.name} is shown in this project again.`);
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, `Could not show this ${noun}.`), "error");
    }
  }

  /** Runs a create, closes the form on success and keeps it open with the message on failure. */
  async function create(run: () => Promise<string | void>, done: string) {
    setCreateError(null);
    try {
      const warning = await run();
      showToast(done);
      if (warning) showToast(warning, "error");
      setCreating(null);
      reload();
    } catch (err) {
      setCreateError(toErrorMessage(err, "Could not create the record."));
    }
  }

  const cancelCreate = () => { setCreating(null); setCreateError(null); };
  const newItems = [
    ...(enabled.includes("persona") ? [{ label: "Persona", onSelect: () => setCreating("persona") }] : []),
    ...(enabled.includes("stakeholder")
      ? [
          { label: "Stakeholder", onSelect: () => setCreating("stakeholder") },
          { label: "Stakeholder from organisation user", onSelect: () => setCreating("stakeholder_from_user") },
        ]
      : []),
    ...(enabled.includes("group") ? [{ label: "Stakeholder Group", onSelect: () => setCreating("group") }] : []),
  ];

  const hiddenControls = enabled.includes("persona") || enabled.includes("stakeholder");

  const newMenu = <MenuButton label="New" primary items={newItems} menuLabel="New person or group" />;
  const tabsStrip = <PeopleTabs projectId={projectId} active="people" hasPeople hasNeeds={hasNeeds} />;
  const kindChips = enabled.length > 1 ? (
      <ToggleChips<PeopleKind>
        ariaLabel="Kinds of record"
        options={enabled.map((k) => ({
          key: k,
          label: PEOPLE_KIND_PLURAL_LABEL[k],
          icon: <PeopleKindIcon kind={k} labelled={false} />,
          count: { persona: personas, stakeholder: stakeholders, group: groups }[k].length,
        }))}
        selected={selected}
        onToggle={toggleKind}
      />
  ) : null;
  /** The page header the lists own, so the filter panel starts at the title (`ListPageLayout`). */
  const page = {
    title: "People",
    actions: newMenu,
    tabs: tabsStrip,
    contentProps: peoplePanelProps("people", true, hasNeeds),
    above: kindChips,
  };

  return (
    <div className="container stack">
      {only === "persona" && (
        <PersonaListView
          personas={personas}
          ariaLabel="Personas"
          sectionKey="stakeholders.personas.list"
          scopeLabel="project"
          emptyText="No Personas recorded for this project yet."
          showScope
          showEffectiveWeight
          typeOptions={typeOptions(personaTypes)}
          includeArchived={includeArchived}
          onIncludeArchivedChange={setIncludeArchived}
          includeHidden={includeHidden}
          onIncludeHiddenChange={setIncludeHidden}
          onShowHidden={(p) => showHidden(p, "persona")}
          onOpen={(p) => openRow(personaRow(p))}
          tagFilter={tagFilterProp}
          projectScope={projectScope}
          page={page}
        />
      )}
      {only === "stakeholder" && (
        <StakeholderListView
          stakeholders={stakeholders}
          ariaLabel="Stakeholders"
          sectionKey="stakeholders.stakeholders.list"
          scopeLabel="project"
          emptyText="No Stakeholders recorded for this project yet."
          showScope
          typeOptions={typeOptions(stakeholderTypes)}
          scheme={scheme}
          groups={ownGroups}
          groupTier="project"
          showLastEngaged
          orgUsers={orgUsers}
          loadHint={(influence, interest) => projectStakeholderApi.cadenceHint(projectId, influence, interest)}
          includeArchived={includeArchived}
          onIncludeArchivedChange={setIncludeArchived}
          includeHidden={includeHidden}
          onIncludeHiddenChange={setIncludeHidden}
          onShowHidden={(s) => showHidden(s, "stakeholder")}
          onOpen={(s) => openRow(stakeholderRow(s))}
          tagFilter={tagFilterProp}
          projectScope={projectScope}
          page={page}
        />
      )}
      {only === "group" && (
        // The group manager is not a filtered list, so it keeps a plain header above it.
        <div className="stack">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h1 style={{ margin: 0 }}>People</h1>
            {newMenu}
          </div>
          {tabsStrip}
          <div className="stack" {...peoplePanelProps("people", true, hasNeeds)}>
            {kindChips}
            <StakeholderGroupsPanel key={refreshKey} projectId={projectId} initialGroupId={params.get("group")} />
          </div>
        </div>
      )}
      {only === null && (
        <PeopleListView
          rows={rows}
          includeArchived={includeArchived}
          onIncludeArchivedChange={setIncludeArchived}
          includeHidden={includeHidden}
          onIncludeHiddenChange={hiddenControls ? setIncludeHidden : undefined}
          onShowHidden={(row) => {
            if (row.kind === "persona" || row.kind === "stakeholder") void showHidden(row.source as Persona | Stakeholder, row.kind);
          }}
          onOpen={openRow}
          tagFilter={tagFilterProp}
          projectScope={projectScope}
          page={page}
        />
      )}

      {creating === "persona" && (
        <PersonaFormModal
          scopeLabel="project" projectId={projectId} typeOptions={typeOptions(personaTypes)} error={createError}
          onCancel={cancelCreate}
          onSave={(values: PersonaFieldValues, quickLinks, tags) =>
            create(async () => {
              const created = await projectPersonaApi.create(projectId, values);
              await commitPersonaLinks(created.id, quickLinks);
              await commitPersonaTags(created.id, tags);
            }, "Persona created.")}
        />
      )}
      {creating === "stakeholder" && (
        <StakeholderFormModal
          scopeLabel="project" projectId={projectId} typeOptions={typeOptions(stakeholderTypes)} scheme={scheme} groups={ownGroups} groupTier="project"
          loadHint={(influence, interest) => projectStakeholderApi.cadenceHint(projectId, influence, interest)}
          error={createError} onCancel={cancelCreate}
          onSave={({ group_ids: groupIds = [], ...values }: StakeholderFieldValues & { group_ids?: string[] }, quickLinks, tags) =>
            create(
              () => createStakeholderWithGroups(
                async (v) => {
                  const created = await projectStakeholderApi.create(projectId, v);
                  await commitStakeholderLinks(created.id, quickLinks);
                  await commitStakeholderTags(created.id, tags);
                  return created;
                },
                (id, ids) => projectStakeholderGroupApi.setStakeholderGroups(projectId, id, ids),
                values, groupIds,
              ).then((warning) => warning ?? undefined),
              "Stakeholder created.",
            )}
        />
      )}
      {creating === "stakeholder_from_user" && (
        <StakeholderFromUserModal
          scopeLabel="project" orgUsers={orgUsers} typeOptions={typeOptions(stakeholderTypes)}
          error={createError} onCancel={cancelCreate}
          onSave={(values) =>
            create(async () => { await projectStakeholderApi.createFromUser(projectId, values); }, "Stakeholder created from user.")}
        />
      )}
      {creating === "group" && (
        <StakeholderGroupFormModal
          groups={ownGroups} error={createError} onCancel={cancelCreate}
          onSave={(values: StakeholderGroupFieldValues) =>
            create(async () => { await projectStakeholderGroupApi.create(projectId, values); }, "Stakeholder group created.")}
        />
      )}
    </div>
  );
}
