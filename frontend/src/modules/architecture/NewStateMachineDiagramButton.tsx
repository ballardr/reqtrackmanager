/**
 * Module: modules/architecture/NewStateMachineDiagramButton
 *
 * The "New state machine diagram" button of an element's Diagrams card: opens the shared diagram form for a state machine
 * diagram with the element preselected (no Type choice) and opens the new diagram's editor once it exists. It is drawn only
 * once the project's modules are known and the state machine sub-component is switched on, since the create would be refused
 * otherwise.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useProjectEnabledModules } from "../../hooks/useProjectEnabledModules";
import { DiagramFormModal } from "./DiagramFormModal";
import { useCreateDiagram } from "./useCreateDiagram";
import type { ArchitectureElement } from "./types";

/** The sub-component that holds state machine diagrams. */
const STATE_MACHINE_SUBCOMPONENT = "architecture_state_machine";

/**
 * @param projectId The element's project.
 * @param element The element the new diagram describes (preselected).
 * @param candidates The elements a state machine diagram may describe (offered in the form).
 */
export function NewStateMachineDiagramButton({
  projectId, element, candidates,
}: { projectId: string; element: ArchitectureElement; candidates: ArchitectureElement[] }) {
  const navigate = useNavigate();
  const { modules, loaded } = useProjectEnabledModules(projectId);
  const [creating, setCreating] = useState(false);
  const form = useCreateDiagram(projectId, (id) => navigate(`/projects/${projectId}/modules/architecture/state-machine-diagrams/${id}`));
  const off = modules.find((m) => m.module_key === "architecture")?.disabled_sub_components?.includes(STATE_MACHINE_SUBCOMPONENT) ?? false;
  if (!loaded || off) return null;
  return (
    <>
      <button className="btn" onClick={() => { form.clearError(); setCreating(true); }}>New state machine diagram</button>
      {creating && (
        <DiagramFormModal
          elements={candidates} projectId={projectId} kinds={["state_machine"]} defaultKind="state_machine" defaultElementId={element.id}
          error={form.error} onCancel={() => { setCreating(false); form.clearError(); }} onSave={form.create}
        />
      )}
    </>
  );
}
