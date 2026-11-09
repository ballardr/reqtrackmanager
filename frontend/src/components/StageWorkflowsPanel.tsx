/**
 * Module: components/StageWorkflowsPanel
 *
 * Administration of stage workflows for one tier, shared by Organisation Admin (the workflows every
 * project of the organisation may use) and Project Admin (the project's own, with the organisation's
 * shown beside them). Lists each workflow as a collapsible row (name, step count and source while closed) that opens to
 * an ordered list of steps, one per phase, with its kind and the starting phase marked; an own-tier workflow can be edited
 * and deleted, and in a project an organisation workflow can be hidden and restored, as every other
 * organisation default can. The server enforces the rules (a phase or workflow in use cannot be removed);
 * its message is shown in the dialog.
 */
import { Pencil, Trash2 } from "lucide-react";
import { useCallback, useState } from "react";

import { api } from "../api/client";
import { STAGE_PHASE_KIND_LABEL, type StageWorkflow } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useMutation } from "../hooks/useMutation";
import { useDisclosureState } from "../hooks/useDisclosureState";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { DisclosureRow } from "./DisclosureRow";
import { RestoreOrgDefaultsButton, type HiddenDefinition } from "./RestoreOrgDefaultsButton";
import { StageWorkflowEditor, type StageWorkflowValues } from "./StageWorkflowEditor";
import { StepIndicator } from "./StepIndicator";

/** Where the panel reads and writes: an organisation's own workflows, or a project's effective set. */
export type StageWorkflowScope = { kind: "organisation"; organizationId: string } | { kind: "project"; projectId: string };

function basePath(scope: StageWorkflowScope): string {
  return scope.kind === "organisation" ? `/api/v1/orgs/${scope.organizationId}/stage-workflows` : `/api/v1/projects/${scope.projectId}/stage-workflows`;
}

/** Who follows a workflow, in words: a project names its stages, the organisation counts across its projects. */
function usedBy(w: StageWorkflow, strings: ReturnType<typeof useStrings>): string {
  const { stage_names: names, stage_count: stages, track_count: tracks, project_count: projects } = w.used_by;
  const s = strings.stageWorkflows;
  if (stages === 0 && tracks === 0) return s.usedByNone;
  if (names.length > 0) return tracks > 0 ? `${s.usedByStages(names)}; ${s.usedByTracks(tracks)}` : s.usedByStages(names);
  return s.usedByCount(stages, tracks, projects);
}

/**
 * @param scope The tier to administer.
 * @param onChanged Called after any change, so a page showing the workflows elsewhere can reload.
 */
export function StageWorkflowsPanel({ scope, onChanged }: { scope: StageWorkflowScope; onChanged?: () => void }) {
  const strings = useStrings();
  const run = useMutation();
  const [workflows, setWorkflows] = useState<StageWorkflow[] | null>(null);
  const [hidden, setHidden] = useState<HiddenDefinition[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<StageWorkflow | "new" | null>(null);
  const [removing, setRemoving] = useState<StageWorkflow | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const path = basePath(scope);
  // One workflow is shown open; several start closed so the one being sought is a named row.
  const disclosure = useDisclosureState(`stageWorkflows:${scope.kind}`, (workflows?.length ?? 0) > 1);
  const ownScope = scope.kind === "organisation" ? "organisation" : "project";

  const reload = useCallback(async () => {
    try {
      setWorkflows(await api.get<StageWorkflow[]>(path));
      setHidden(scope.kind === "project" ? await api.get<HiddenDefinition[]>(`${path}/hidden`) : []);
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, strings.stageWorkflows.loadFailed));
    }
  }, [path, scope.kind, strings.stageWorkflows.loadFailed]);

  useLoadOnChange(reload, [path]);

  async function save(values: StageWorkflowValues) {
    setSaveError(null);
    const existing = editing !== "new" ? editing : null;
    try {
      if (existing) await api.put(`${path}/${existing.id}`, values);
      else await api.post(path, values);
    } catch (err) {
      setSaveError(toErrorMessage(err, strings.mutation.failure("save", strings.stageWorkflows.nounSingular)));
      return;
    }
    setEditing(null);
    await reload();
    onChanged?.();
  }

  async function remove(workflow: StageWorkflow) {
    setRemoving(null);
    const verb = workflow.scope === ownScope ? "delete" : "remove";
    if (!(await run(() => api.delete(`${path}/${workflow.id}`), verb, strings.stageWorkflows.nounSingular))) return;
    await reload();
    onChanged?.();
  }

  async function restore(ids: string[]) {
    await api.post(`${path}/restore`, { workflow_ids: ids });
    await reload();
    onChanged?.();
  }

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (!workflows) return null;
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "flex-end" }}>
        {scope.kind === "project" && (
          <RestoreOrgDefaultsButton hidden={hidden} noun={strings.stageWorkflows.nounPlural} onRestore={restore} />
        )}
        <button className="btn btn-primary" onClick={() => { setSaveError(null); setEditing("new"); }}>
          {strings.stageWorkflows.newWorkflow}
        </button>
      </div>
      {workflows.length === 0 && <div className="text-muted">{strings.stageWorkflows.noWorkflows}</div>}
      {workflows.map((w) => {
        const own = w.scope === ownScope;
        return (
          <DisclosureRow
            key={w.id}
            collapsed={disclosure.isCollapsed(w.id)} onToggle={() => disclosure.toggle(w.id)}
            title={w.name}
            summary={
              <>
                {strings.stageWorkflows.stepCount(w.phases.length)}
                {scope.kind === "project" && (
                  <> <Badge>{own ? strings.stageWorkflows.scopeProject : strings.stageWorkflows.scopeOrganisation}</Badge></>
                )}
              </>
            }
            actions={
              <>
                {own && (
                  <button
                    className="btn" aria-label={strings.stageWorkflows.editAria(w.name)} title={strings.stageWorkflows.editAria(w.name)}
                    onClick={() => { setSaveError(null); setEditing(w); }}
                  >
                    <Pencil />
                  </button>
                )}
                <button
                  className="btn btn-danger"
                  aria-label={own ? strings.stageWorkflows.deleteAria(w.name) : strings.stageWorkflows.hideAria(w.name)}
                  title={own ? strings.stageWorkflows.deleteAria(w.name) : strings.stageWorkflows.hideAria(w.name)}
                  onClick={() => setRemoving(w)}
                >
                  <Trash2 />
                </button>
              </>
            }
          >
            <span className="text-muted" style={{ fontSize: "0.85rem" }}>{usedBy(w, strings)}</span>
            <StepIndicator
              vertical label={strings.stageWorkflows.stepsAria(w.name)} steps={w.phases.map((p) => p.name)}
              details={w.phases.map((p, index) => [
                p.name.toLowerCase() === STAGE_PHASE_KIND_LABEL[p.kind].toLowerCase() ? undefined : STAGE_PHASE_KIND_LABEL[p.kind],
                index === 0 ? strings.stageWorkflows.startStep : undefined,
              ].filter(Boolean).join(" · ") || undefined)}
            />
          </DisclosureRow>
        );
      })}
      {editing !== null && (
        <StageWorkflowEditor
          workflow={editing === "new" ? null : editing} error={saveError} onCancel={() => setEditing(null)} onSave={save}
        />
      )}
      {removing && (
        <ConfirmDialog
          title={removing.scope === ownScope ? strings.stageWorkflows.deleteTitle(removing.name) : strings.stageWorkflows.hideTitle(removing.name)}
          message={removing.scope === ownScope ? strings.stageWorkflows.deleteBody : strings.stageWorkflows.hideBody}
          confirmLabel={removing.scope === ownScope ? strings.common.delete : strings.stageWorkflows.hideConfirm}
          onConfirm={() => remove(removing)} onCancel={() => setRemoving(null)}
        />
      )}
    </div>
  );
}
