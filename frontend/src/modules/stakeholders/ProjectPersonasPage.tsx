/**
 * Module: modules/stakeholders/ProjectPersonasPage
 *
 * The project-scoped Persona list route, mounted at
 * `/projects/:projectId/modules/stakeholders/personas` (`module.ts`, reached
 * via the "Personas" nav-rail entry). Lists the project's own personas *and*
 * the organisation's live ones (Phase 0 resolution 2), each with this
 * project's effective weight; new personas created here are project-scoped.
 * The list/filter/create UI is the shared `PersonaListView`. Every row opens
 * inside this project (an org persona too), so its weight override stays
 * reachable; `PersonaDetailPage` makes an org persona read-only there.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectPersonaApi } from "./api";
import { PersonaListView } from "./PersonaListView";
import type { EffectivePersonaType, Persona } from "./types";

export function ProjectPersonasPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [personas, setPersonas] = useState<Persona[] | null>(null);
  const [types, setTypes] = useState<EffectivePersonaType[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);

  const [refreshKey, setRefreshKey] = useState(0);
  const reload = () => setRefreshKey((k) => k + 1);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    Promise.all([
      projectPersonaApi.list(projectId, { include_archived: includeArchived }),
      projectPersonaApi.listTypes(projectId),
    ])
      .then(([list, typeList]) => {
        if (!active) return;
        setPersonas(list);
        setTypes(typeList);
        setLoadError(null);
      })
      .catch((err) => {
        if (active) setLoadError(toErrorMessage(err, "The Stakeholders & Personas module isn't enabled for this project's organisation, or you don't have access to it."));
      });
    return () => {
      active = false;
    };
  }, [projectId, includeArchived, refreshKey]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (personas === null) return <Spinner />;

  return (
    <div className="container stack">
      <h1 style={{ margin: 0 }}>Personas</h1>
      <PersonaListView
        personas={personas}
        ariaLabel="Personas"
        sectionKey="stakeholders.personas.list"
        scopeLabel="project"
        emptyText="No Personas recorded for this project yet."
        showScope
        showEffectiveWeight
        typeOptions={types.filter((t) => t.is_enabled).map((t) => ({ value: t.id, label: t.name }))}
        includeArchived={includeArchived}
        onIncludeArchivedChange={setIncludeArchived}
        onOpen={(p) => navigate(`/projects/${projectId}/modules/stakeholders/personas/${p.id}`)}
        onCreate={async (values) => {
          await projectPersonaApi.create(projectId, values);
          showToast("Persona created.");
          reload();
        }}
      />
    </div>
  );
}
