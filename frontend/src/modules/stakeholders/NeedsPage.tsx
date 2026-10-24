/**
 * Module: modules/stakeholders/NeedsPage
 *
 * The project's Stakeholder Needs list, mounted at `/projects/:projectId/modules/stakeholders/needs` and
 * reached from the "Needs" tab beside People (`PeopleTabs`). Needs are not people, so they have their own
 * list, filters and New button; the Need detail page and the needs a Stakeholder holds are unchanged.
 * If the project has switched Needs off the page says so; if it has no Persona, Stakeholder or Group kind
 * on, this is the only tab and the nav's People entry lands here.
 */
import { useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { rowProjectId } from "../../api/projectScope";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useProjectEnabledModules } from "../../hooks/useProjectEnabledModules";
import { useProjectScope } from "../../hooks/useProjectScope";
import { useTagFilter } from "../../hooks/useTagFilter";
import { projectNeedApi } from "./api";
import { NeedFormModal } from "./NeedFormModal";
import { NeedListView } from "./NeedListView";
import { enabledKinds, needsEnabled } from "./peopleRows";
import { PeopleTabs } from "./PeopleTabs";
import { peoplePanelProps } from "./peopleTabState";
import type { Need, NeedFieldValues } from "./types";

const MODULE_KEY = "stakeholders";
const NOT_AVAILABLE =
  "Stakeholder Needs aren't enabled for this project, or you don't have access to them.";

export function NeedsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const commitLinks = useCommitQuickLinks(projectId ?? "", "stakeholder_need");
  const commitTags = useCommitTags(projectId ?? "", "stakeholder_need");
  const { modules, loaded } = useProjectEnabledModules(projectId ?? null);
  const disabled = modules.find((m) => m.module_key === MODULE_KEY)?.disabled_sub_components ?? [];
  const hasNeeds = needsEnabled(disabled);
  const hasPeople = enabledKinds(disabled).length > 0;

  const [needs, setNeeds] = useState<Need[]>([]);
  const [data, setData] = useState<"loading" | "ready">("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  /** Counts loads so a slow, superseded response never replaces a newer one. */
  const loadSeq = useRef(0);

  useLoadOnChange(
    () => {
      if (!projectId || !loaded || !hasNeeds) return;
      const mine = ++loadSeq.current;
      projectNeedApi
        .list(projectId, { include_archived: includeArchived, tags: tagFilter.tags, tag_mode: tagFilter.mode, project_scope: projectScope.scope })
        .then((list) => {
          if (mine !== loadSeq.current) return;
          setNeeds(list);
          setLoadError(null);
          setData("ready");
        })
        .catch((err) => {
          if (mine === loadSeq.current) setLoadError(toErrorMessage(err, NOT_AVAILABLE));
        });
    },
    [projectId, loaded, hasNeeds, includeArchived, refreshKey, tagFilter.query, projectScope.scope],
  );

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (!loaded || (hasNeeds && data === "loading")) return <Spinner />;
  if (!hasNeeds) return <p className="text-muted">{NOT_AVAILABLE}</p>;

  /** Runs the create, closes the form on success and keeps it open with the message on failure. */
  async function create(values: NeedFieldValues, quickLinks: Parameters<typeof commitLinks>[1], tags: string[]) {
    setCreateError(null);
    try {
      const created = await projectNeedApi.create(projectId!, values);
      await commitLinks(created.id, quickLinks);
      await commitTags(created.id, tags);
      showToast("Stakeholder Need created.");
      setCreating(false);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setCreateError(toErrorMessage(err, "Could not create the record."));
    }
  }

  return (
    <div className="container stack">
      <NeedListView
        needs={needs}
        ariaLabel="Stakeholder Needs"
        sectionKey="stakeholders.needs.list"
        emptyText="No Stakeholder Needs recorded for this project yet."
        includeArchived={includeArchived}
        onIncludeArchivedChange={setIncludeArchived}
        onOpen={(need) => navigate(`/projects/${rowProjectId(need, projectId)}/modules/stakeholders/needs/${need.id}`)}
        tagFilter={{ projectId, filter: tagFilter }}
        exportRecords={{ projectId, onImported: () => setRefreshKey((k) => k + 1) }}
        projectScope={projectScope}
        page={{
          title: hasPeople ? "People" : "Needs",
          actions: (
            <button type="button" className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
              New Stakeholder Need
            </button>
          ),
          tabs: <PeopleTabs projectId={projectId} active="needs" hasPeople={hasPeople} hasNeeds={hasNeeds} />,
          contentProps: peoplePanelProps("needs", hasPeople, hasNeeds),
        }}
      />
      {creating && (
        <NeedFormModal
          projectId={projectId} error={createError} onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={(values: NeedFieldValues, quickLinks, tags) => create(values, quickLinks ?? [], tags ?? [])}
        />
      )}
    </div>
  );
}
