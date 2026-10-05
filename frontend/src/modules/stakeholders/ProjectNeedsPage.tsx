/**
 * Module: modules/stakeholders/ProjectNeedsPage
 *
 * The project's Stakeholder Need list route, mounted at
 * `/projects/:projectId/modules/stakeholders/needs` (`module.ts`, reached via the
 * "Needs" nav-rail entry). A need is always project-scoped, so unlike the
 * Persona and Stakeholder lists there is no organisation half, type or scope
 * column; the list/filter/create UI is the shared `RecordListView`. Status
 * renders through `NEED_STATUS_LABEL`.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectNeedApi } from "./api";
import { NeedFormModal } from "./NeedFormModal";
import { RecordListView } from "./RecordListView";
import type { Need, NeedFieldValues } from "./types";
import { NEED_STATUS_LABEL, NEED_STATUS_TONE } from "./types";

export function ProjectNeedsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [needs, setNeeds] = useState<Need[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);

  const [refreshKey, setRefreshKey] = useState(0);
  const reload = () => setRefreshKey((k) => k + 1);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    projectNeedApi
      .list(projectId, { include_archived: includeArchived })
      .then((list) => {
        if (!active) return;
        setNeeds(list);
        setLoadError(null);
      })
      .catch((err) => {
        if (active) setLoadError(toErrorMessage(err, "Stakeholder Needs aren't enabled for this project, or you don't have access to them."));
      });
    return () => {
      active = false;
    };
  }, [projectId, includeArchived, refreshKey]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (needs === null) return <Spinner />;

  return (
    <div className="container stack">
      <h1 style={{ margin: 0 }}>Stakeholder Needs</h1>
      <RecordListView<Need, NeedFieldValues>
        records={needs}
        ariaLabel="Stakeholder Needs"
        sectionKey="stakeholders.needs.list"
        noun="Need"
        scopeLabel="project"
        emptyText="No Stakeholder Needs recorded for this project yet."
        showScope={false}
        statusLabel={NEED_STATUS_LABEL}
        statusTone={NEED_STATUS_TONE}
        searchText={(n) => `${n.name} ${n.description}`}
        columnsBeforeType={[{ key: "need", label: "Need", render: (n) => n.description || "—" }]}
        columnsAfterScope={[]}
        includeArchived={includeArchived}
        onIncludeArchivedChange={setIncludeArchived}
        onOpen={(n) => navigate(`/projects/${projectId}/modules/stakeholders/needs/${n.id}`)}
        onCreate={async (values) => {
          await projectNeedApi.create(projectId, values);
          showToast("Stakeholder Need created.");
          reload();
        }}
        renderCreateModal={(props) => <NeedFormModal error={props.error} onCancel={props.onCancel} onSave={props.onSave} />}
      />
    </div>
  );
}
