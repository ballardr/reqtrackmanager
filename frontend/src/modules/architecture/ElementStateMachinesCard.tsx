/**
 * Module: modules/architecture/ElementStateMachinesCard
 *
 * The "State machine diagrams" card of an element's page: the state machine diagrams that describe the element, each a link to
 * its editor with its status and state count, and a New button that opens the shared diagram form for a state machine diagram
 * with this element preselected (the Type choice is not offered here). The card is drawn only for a person who can read state
 * machine diagrams: a list that answers 403 or 404 leaves it out, so the page is unchanged for everyone else.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Badge } from "../../components/Badge";
import { DetailCard } from "../../components/DetailCard";
import { ScopedRecordCode } from "../../components/ScopedRecordCode";
import { projectStateMachineApi } from "./api";
import { DiagramFormModal } from "./DiagramFormModal";
import { useCreateDiagram } from "./useCreateDiagram";
import { ARCHITECTURE_STATUS_LABEL, ARCHITECTURE_STATUS_TONE, type ArchitectureElement, type StateMachineDiagram } from "./types";

/**
 * @param projectId The element's project.
 * @param element The element the diagrams describe.
 * @param candidates The elements a state machine diagram may describe (offered in the form; this one is preselected).
 * @param readOnly True for an archived element: no New button (a person may describe an element shared with them).
 */
export function ElementStateMachinesCard({
  projectId, element, candidates, readOnly,
}: {
  projectId: string;
  element: ArchitectureElement;
  candidates: ArchitectureElement[];
  readOnly: boolean;
}) {
  const navigate = useNavigate();
  const [diagrams, setDiagrams] = useState<StateMachineDiagram[] | null>(null);
  const [creating, setCreating] = useState(false);
  const form = useCreateDiagram(projectId, (id) => navigate(`/projects/${projectId}/modules/architecture/state-machine-diagrams/${id}`));
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    let live = true;
    projectStateMachineApi(projectId).list({ element_id: element.id })
      .then((list) => { if (live) setDiagrams(list); })
      .catch(() => { if (live) setDiagrams(null); });
    return () => { live = false; };
  }, [projectId, element.id, refreshKey]);

  if (diagrams === null) return null;
  return (
    <>
      <DetailCard
        heading="State machine diagrams"
        action={readOnly ? undefined : <button className="btn" onClick={() => { form.clearError(); setCreating(true); }}>New state machine diagram</button>}
      >
        {diagrams.length === 0 ? <p className="text-muted" style={{ margin: 0 }}>No state machine diagrams.</p> : (
          <ul style={{ margin: 0, paddingLeft: 0, listStyle: "none" }} className="stack">
            {diagrams.map((d) => (
              <li key={d.id}>
                <Link to={`/projects/${projectId}/modules/architecture/state-machine-diagrams/${d.id}`}>
                  <ScopedRecordCode record={{ unique_code: d.unique_code, from_project_code: d.from_project_code }} /> {d.name}
                </Link>{" "}
                <Badge tone={ARCHITECTURE_STATUS_TONE[d.status]}>{ARCHITECTURE_STATUS_LABEL[d.status]}</Badge>{" "}
                <span className="text-muted">{d.state_count} {d.state_count === 1 ? "state" : "states"}</span>
              </li>
            ))}
          </ul>
        )}
      </DetailCard>
      {creating && (
        <DiagramFormModal
          elements={candidates} projectId={projectId} kinds={["state_machine"]} defaultKind="state_machine" defaultElementId={element.id}
          error={form.error} onCancel={() => { setCreating(false); form.clearError(); reload(); }} onSave={form.create}
        />
      )}
    </>
  );
}
