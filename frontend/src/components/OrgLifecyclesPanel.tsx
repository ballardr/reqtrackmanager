/**
 * Module: components/OrgLifecyclesPanel
 *
 * The Lifecycles group of Organisation Administration: a switch that forbids skipping steps on a record in every
 * project (with the projects exempt from it), then for each record type of an enabled module that has optional states,
 * a checkbox per state that makes it required in every project of the organisation, and the projects that are exempt
 * from the requirement.
 *
 * Responsibilities:
 * - Read the organisation's lifecycles and skip rule and save them: one type's required states, the ban on skipping,
 *   and the exemptions of each (`LifecyclesApi`); `api` and `loadProjects` are injectable for stories.
 * - Offer an exemption through a dialog (a project and whether its nested projects are exempt too), never as empty fields
 *   in the layout. The list of exempt projects and the dialog are one component for the ban and for each type.
 *
 * Design decisions: a required state binds every project, including nested ones; an exempt project keeps its own choice
 * (see `ProjectLifecyclesPanel`). Only an optional state can be required.
 */
import { Trash2 } from "lucide-react";
import { useCallback, useState } from "react";

import { api as http } from "../api/client";
import { lifecyclesApi, type LifecycleExemption, type LifecyclesApi, type OrgLifecycle, type OrgSkip } from "../api/lifecycles";
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
  const [skip, setSkip] = useState<OrgSkip | null>(null);
  const [failed, setFailed] = useState(false);
  /** The type whose exemption is being added; `"skip"` is the ban on skipping steps. */
  const [exempting, setExempting] = useState<OrgLifecycle | "skip" | null>(null);

  const load = useCallback(async () => {
    try {
      const [loadedTypes, loadedSkip] = await Promise.all([api.organization(organizationId), api.organizationSkip(organizationId)]);
      setTypes(loadedTypes);
      setSkip(loadedSkip);
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

  /** The same for a change to the skip rule. */
  async function runSkip(action: () => Promise<OrgSkip>, message: string): Promise<boolean> {
    try {
      setSkip(await action());
      showToast(message);
      return true;
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
      return false;
    }
  }

  if (failed && (!types || !skip)) return <p className="text-muted" role="alert">{text.loadFailed}</p>;
  if (!types || !skip) return <Spinner />;

  return (
    <div className="stack">
      <section className="stack" aria-label={text.skipHeading}>
        <h3 style={{ margin: 0 }}>{text.skipHeading}</h3>
        <CheckboxField
          label={text.forbidSkip} help={strings.help.lifecycleSkipForbidden} checked={skip.forbidden}
          onChange={(on) => void runSkip(() => api.setSkipForbidden(organizationId, on), text.saved)}
        />
        <ExemptionList
          exemptions={skip.exemptions} onAdd={() => setExempting("skip")}
          onRemove={(projectId) => void runSkip(() => api.removeSkipExemption(organizationId, projectId), text.exemptionRemoved)}
        />
      </section>
      {types.length === 0 && <p className="text-muted">{text.noTypes}</p>}
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
          <ExemptionList
            exemptions={type.exemptions} onAdd={() => setExempting(type)}
            onRemove={(projectId) => void run(() => api.removeExemption(organizationId, type.artefact_type, projectId), text.exemptionRemoved)}
          />
        </section>
      ))}
      {exempting && (
        <ExemptionDialog
          title={exempting === "skip" ? text.skipExemptTitle : text.addExemptionTitle(exempting.label)}
          taken={new Set((exempting === "skip" ? skip.exemptions : exempting.exemptions).map((e) => e.project_id))}
          organizationId={organizationId} loadProjects={loadProjects} onClose={() => setExempting(null)}
          onSave={(projectId, includeChildren) => exempting === "skip"
            ? runSkip(() => api.addSkipExemption(organizationId, projectId, includeChildren), text.exemptionAdded)
            : run(() => api.addExemption(organizationId, exempting.artefact_type, projectId, includeChildren), text.exemptionAdded)}
        />
      )}
    </div>
  );
}

/** The projects exempt from a requirement or from the ban on skipping steps, each removable, and the button that adds one. */
function ExemptionList({
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
function ExemptionDialog({
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
