/**
 * Module: components/OrgLifecyclesPanel
 *
 * The Lifecycles group of Organisation Administration: for each record type of an enabled module that has optional
 * states, a checkbox per state that makes it required in every project of the organisation, and the projects that are
 * exempt from the requirement.
 *
 * Responsibilities:
 * - Read the organisation's lifecycles and save one type's required states, add and remove an exemption
 *   (`LifecyclesApi`); `api` and `loadProjects` are injectable for stories.
 * - Offer an exemption through a dialog (a project and whether its nested projects are exempt too), never as empty fields
 *   in the layout.
 *
 * Design decisions: a required state binds every project, including nested ones; an exempt project keeps its own choice
 * (see `ProjectLifecyclesPanel`). Only an optional state can be required.
 */
import { Trash2 } from "lucide-react";
import { useCallback, useState } from "react";

import { api as http } from "../api/client";
import { lifecyclesApi, type LifecyclesApi, type OrgLifecycle } from "../api/lifecycles";
import type { Project } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { Badge } from "./Badge";
import { CellText } from "./CellText";
import { CheckboxField } from "./FormFields";
import { FormActions } from "./FormActions";
import { IconAction } from "./IconAction";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";

/** Loads the organisation's projects for the exemption dialog. */
export type LoadOrgProjects = (organizationId: string) => Promise<Array<Pick<Project, "id" | "name" | "code">>>;

const loadOrgProjects: LoadOrgProjects = (organizationId) =>
  http.get<Project[]>(`/api/v1/projects?organization_id=${organizationId}`);

/**
 * @param organizationId The organisation whose lifecycles are configured.
 * @param api The calls (the live ones by default).
 * @param loadProjects Lists the organisation's projects for the exemption dialog (the live call by default).
 */
export function OrgLifecyclesPanel({
  organizationId, api = lifecyclesApi, loadProjects = loadOrgProjects,
}: { organizationId: string; api?: LifecyclesApi; loadProjects?: LoadOrgProjects }) {
  const strings = useStrings();
  const text = strings.lifecycleSettings;
  const { showToast } = useToast();
  const [types, setTypes] = useState<OrgLifecycle[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [exempting, setExempting] = useState<OrgLifecycle | null>(null);

  const load = useCallback(async () => {
    try {
      setTypes(await api.organization(organizationId));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [api, organizationId]);
  useLoadOnChange(load, [api, organizationId]);

  /** Runs a change, shows its outcome and reports whether it succeeded. */
  async function run(action: () => Promise<OrgLifecycle[]>, message: string): Promise<boolean> {
    try {
      setTypes(await action());
      showToast(message);
      return true;
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
      return false;
    }
  }

  if (failed && !types) return <p className="text-muted" role="alert">{text.loadFailed}</p>;
  if (!types) return <Spinner />;
  if (types.length === 0) return <p className="text-muted">{text.noTypes}</p>;

  return (
    <div className="stack">
      {types.map((type) => (
        <section key={type.artefact_type} className="stack" aria-label={type.label}>
          <h3 style={{ margin: 0 }}>{text.typeOf(type.label, type.module_name)}</h3>
          <div className="row" style={{ alignItems: "flex-start" }}>
            {type.states.map((state) => (
              <CheckboxField
                key={state.key} label={text.requireState(state.label)} help={strings.help.lifecycleRequired}
                checked={type.required.includes(state.key)}
                onChange={(on) => {
                  const next = type.states.map((s) => s.key).filter((k) => (k === state.key ? on : type.required.includes(k)));
                  void run(() => api.setRequired(organizationId, type.artefact_type, next), text.saved);
                }}
              />
            ))}
          </div>
          <div className="stack" style={{ gap: "var(--space-1)" }}>
            <strong>{text.exemptHeading}</strong>
            {type.exemptions.length === 0 ? (
              <span className="text-muted">{text.noExemptions}</span>
            ) : (
              <ul className="stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: "var(--space-1)" }}>
                {type.exemptions.map((ex) => (
                  <li key={ex.project_id} className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }} data-stress-row>
                    <span style={{ minWidth: 0 }}>
                      <CellText>{`${ex.project_code} ${ex.project_name}`}</CellText>
                      {ex.include_children && <> <Badge>{text.includesChildren}</Badge></>}
                    </span>
                    <span style={{ flex: "none" }}>
                      <IconAction
                        label={text.removeExemption(ex.project_name)}
                        onClick={() => void run(() => api.removeExemption(organizationId, type.artefact_type, ex.project_id), text.exemptionRemoved)}
                      >
                        <Trash2 size={14} />
                      </IconAction>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <div>
              <button type="button" className="btn" onClick={() => setExempting(type)}>{text.addExemption}</button>
            </div>
          </div>
        </section>
      ))}
      {exempting && (
        <ExemptionDialog
          type={exempting} organizationId={organizationId} loadProjects={loadProjects} onClose={() => setExempting(null)}
          onSave={(projectId, includeChildren) =>
            run(() => api.addExemption(organizationId, exempting.artefact_type, projectId, includeChildren), text.exemptionAdded)}
        />
      )}
    </div>
  );
}

/** The dialog that exempts one project (and optionally its nested projects) from a type's required states. */
function ExemptionDialog({
  type, organizationId, loadProjects, onSave, onClose,
}: {
  type: OrgLifecycle; organizationId: string; loadProjects: LoadOrgProjects;
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

  const taken = new Set(type.exemptions.map((e) => e.project_id));
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
    <Modal title={text.addExemptionTitle(type.label)} onClose={onClose}>
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
