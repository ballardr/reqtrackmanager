/**
 * Module: components/LifecycleExemptions
 *
 * The exempt-project list and the dialog that adds one, shared by every organisation rule that a project can be exempt
 * from (required states, the ban on skipping steps, a required separate approver).
 *
 * Responsibilities:
 * - List the exempt projects, each removable, with the button that opens the dialog (`ExemptionList`).
 * - Add one project, and whether its nested projects are exempt too, through a dialog (`ExemptionDialog`), never as
 *   empty fields in the layout.
 *
 * Design decisions: the components hold no data of their own; the caller owns the calls so each rule keeps its own
 * endpoint. The organisation's projects are loaded through an injectable `LoadOrgProjects` for stories.
 */
import { Trash2 } from "lucide-react";
import { useCallback, useState } from "react";

import type { LifecycleExemption, LoadOrgProjects } from "../api/lifecycles";
import type { Project } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { Badge } from "./Badge";
import { CellText } from "./CellText";
import { CheckboxField } from "./FormFields";
import { FormActions } from "./FormActions";
import { IconAction } from "./IconAction";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";

/** The projects exempt from a requirement or from the ban on skipping steps, each removable, and the button that adds one. */
export function ExemptionList({
  exemptions, onAdd, onRemove,
}: { exemptions: LifecycleExemption[]; onAdd: () => void; onRemove: (projectId: string) => void }) {
  const strings = useStrings();
  const text = strings.lifecycleSettings;
  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <strong>{text.exemptHeading}</strong>
      {exemptions.length === 0 ? (
        <span className="text-muted">{text.noExemptions}</span>
      ) : (
        <ul className="stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: "var(--space-1)" }}>
          {exemptions.map((ex) => (
            <li key={ex.project_id} className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }} data-stress-row>
              <span style={{ minWidth: 0 }}>
                <CellText>{`${ex.project_code} ${ex.project_name}`}</CellText>
                {ex.include_children && <> <Badge>{text.includesChildren}</Badge></>}
              </span>
              <span style={{ flex: "none" }}>
                <IconAction label={text.removeExemption(ex.project_name)} onClick={() => onRemove(ex.project_id)}>
                  <Trash2 size={14} />
                </IconAction>
              </span>
            </li>
          ))}
        </ul>
      )}
      <div>
        <button type="button" className="btn" onClick={onAdd}>{text.addExemption}</button>
      </div>
    </div>
  );
}

/** The dialog that exempts one project (and optionally its nested projects) from a requirement or from the ban on skipping steps. */
export function ExemptionDialog({
  title, taken, organizationId, loadProjects, onSave, onClose,
}: {
  title: string; taken: ReadonlySet<string>; organizationId: string; loadProjects: LoadOrgProjects;
  onSave: (projectId: string, includeChildren: boolean) => Promise<boolean>; onClose: () => void;
}) {
  const strings = useStrings();
  const text = strings.lifecycleSettings;
  const [projects, setProjects] = useState<Array<Pick<Project, "id" | "name" | "code">>>([]);
  const [projectId, setProjectId] = useState("");
  const [includeChildren, setIncludeChildren] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setProjects(await loadProjects(organizationId));
    } catch {
      setProjects([]);
    }
  }, [loadProjects, organizationId]);
  useLoadOnChange(load, [organizationId]);

  const options = projects.filter((p) => !taken.has(p.id)).map((p) => ({ value: p.id, label: `${p.code} ${p.name}` }));

  async function submit() {
    setBusy(true);
    try {
      if (await onSave(projectId, includeChildren)) onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={title} onClose={onClose}>
      <div className="stack">
        <LabeledSelect
          required label={text.projectLabel} help={strings.help.lifecycleExemptProject} value={projectId} options={options}
          onChange={setProjectId}
        />
        <CheckboxField label={text.includeChildren} help={strings.help.lifecycleIncludeChildren} checked={includeChildren} onChange={setIncludeChildren} />
        <FormActions onCancel={onClose} onSave={() => void submit()} saveLabel={text.addExemption} saveDisabled={busy || projectId === ""} cancelDisabled={busy} />
      </div>
    </Modal>
  );
}
