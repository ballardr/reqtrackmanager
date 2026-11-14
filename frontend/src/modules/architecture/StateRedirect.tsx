/**
 * Module: modules/architecture/StateRedirect
 *
 * The page a link to a state follows (`/projects/:projectId/modules/architecture/states/:stateId`): a state has no page of
 * its own, so it reads the state and replaces itself with its state machine diagram, opened with that state selected. A state
 * that cannot be read (absent, or its element not visible to the person) shows a not-found message, never a spinner.
 */
import { useEffect, useState } from "react";
import { Navigate, useParams } from "react-router-dom";

import { Spinner } from "../../components/Spinner";
import { projectStateApi } from "./api";

export function StateRedirect() {
  const { projectId = "", stateId = "" } = useParams<{ projectId: string; stateId: string }>();
  const [target, setTarget] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let live = true;
    projectStateApi(projectId).get(stateId)
      .then((state) => { if (live) setTarget(`/projects/${projectId}/modules/architecture/state-machine-diagrams/${state.state_machine_diagram_id}?state=${state.id}`); })
      .catch(() => { if (live) setMissing(true); });
    return () => { live = false; };
  }, [projectId, stateId]);

  if (missing) return <p className="text-muted">This state could not be found, or you do not have access to it.</p>;
  if (target === null) return <Spinner />;
  return <Navigate to={target} replace />;
}
