/**
 * Module: modules/architecture/ProjectSharingPage
 *
 * The project's collections at `/projects/:projectId/modules/architecture/sharing`: the page where an architect chooses
 * which of the project's elements other projects and groups may use, and with whom. It is reached from the Elements
 * list; the work is `CollectionsPanel`.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Spinner } from "../../components/Spinner";
import { toErrorMessage } from "../../context/ToastContext";
import { architectureTabPath } from "./architectureTabs";
import { projectElementApi } from "./api";
import { CollectionsPanel } from "./CollectionsPanel";
import { useArchitectureReference } from "./useArchitectureReference";
import type { ArchitectureElement } from "./types";

export function ProjectSharingPage() {
  const { projectId = "" } = useParams<{ projectId: string }>();
  const reference = useArchitectureReference(projectId);
  const [elements, setElements] = useState<ArchitectureElement[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const scope = useMemo(() => ({ kind: "project" as const, projectId }), [projectId]);

  useEffect(() => {
    if (!projectId) return;
    let live = true;
    projectElementApi(projectId).list({ open_only: true })
      .then((list) => { if (live) setElements(list); })
      .catch((err) => { if (live) setLoadError(toErrorMessage(err, "System Architecture is not enabled for this project, or you do not have access to it.")); });
    return () => { live = false; };
  }, [projectId]);

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (elements === null || !reference.loaded || reference.project === null) return <Spinner />;
  return (
    <div className="container stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
        <h1>Sharing</h1>
        <Link to={architectureTabPath(projectId, "elements")}>Elements</Link>
      </div>
      <CollectionsPanel scope={scope} elements={elements} orgUsers={reference.orgUsers} organizationId={reference.project.organization_id} />
    </div>
  );
}
