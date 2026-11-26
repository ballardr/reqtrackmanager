/**
 * Module: modules/traceability/ProfileLifecycleTab
 *
 * The Lifecycle tab of a governance profile: the optional states the profile requires of each record type, whether it
 * forbids skipping steps and the organisation stage workflow it requires of new stages.
 *
 * Responsibilities: load the profile's lifecycle and stage workflow policy, save each part with its own control and show
 * the response as the new state. Required states are chosen in a dialog per record type; the skipping rule is a single
 * setting that acts at once; the stage workflow is one settings group with one Save and a confirmed removal.
 *
 * Design decisions: every part of the organisation router needs the organisation governance permission, so every control
 * is editable. A record type with no optional state is absent from the response, so the table lists only types that can
 * be required. With no organisation stage workflow the section says so and offers no empty choice.
 *
 * Dependencies: `profileApi` (`./api`), `PolicyTable`, `LifecycleRequiredModal`, `SettingsForm`, `ConfirmDialog`.
 */
import { useCallback, useState } from "react";

import { Badge } from "../../components/Badge";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { FieldCaption } from "../../components/FieldHelp";
import { CheckboxField } from "../../components/FormFields";
import { LabeledSelect } from "../../components/LabeledSelect";
import { LoadFailed } from "../../components/LoadFailed";
import { SettingsForm } from "../../components/SettingsForm";
import { Spinner } from "../../components/Spinner";
import { useToast } from "../../context/ToastContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useMutation } from "../../hooks/useMutation";
import { profileApi } from "./api";
import { GOVERNANCE_HELP } from "./help";
import { LifecycleRequiredModal } from "./LifecycleRequiredModal";
import { PolicyTable } from "./PolicyTable";
import {
  STAGE_WORKFLOW_MODE_LABEL,
  type LifecycleTypePolicy,
  type ProfileLifecycle,
  type ProfileStageWorkflow,
  type StageWorkflowMode,
} from "./types";

const MODE_OPTIONS = (Object.keys(STAGE_WORKFLOW_MODE_LABEL) as StageWorkflowMode[]).map((value) => ({
  value, label: STAGE_WORKFLOW_MODE_LABEL[value],
}));

/**
 * @param row One record type's requirement.
 * @returns The labels of the states it requires, in path order.
 */
function requiredLabels(row: LifecycleTypePolicy): string[] {
  return row.states.filter((s) => row.required.includes(s.key)).map((s) => s.label);
}

/**
 * @param orgId The organisation that owns the profile.
 * @param profileId The profile whose lifecycle policy is shown.
 */
export function ProfileLifecycleTab({ orgId, profileId }: { orgId: string; profileId: string }) {
  const { showToast } = useToast();
  const run = useMutation();
  const [lifecycle, setLifecycle] = useState<ProfileLifecycle | null>(null);
  const [workflow, setWorkflow] = useState<ProfileStageWorkflow | null>(null);
  const [failed, setFailed] = useState(false);
  const [editing, setEditing] = useState<LifecycleTypePolicy | null>(null);
  const [removing, setRemoving] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    try {
      const [loadedLifecycle, loadedWorkflow] = await Promise.all([
        profileApi.lifecycle(orgId, profileId), profileApi.stageWorkflow(orgId, profileId),
      ]);
      setLifecycle(loadedLifecycle);
      setWorkflow(loadedWorkflow);
    } catch {
      setFailed(true);
    }
  }, [orgId, profileId]);
  useLoadOnChange(load, [orgId, profileId]);

  async function saveRequired(type: LifecycleTypePolicy, required: string[]) {
    setLifecycle(await profileApi.setLifecycleRequired(orgId, profileId, type.artefact_type, required));
    showToast(`Required states of ${type.label} saved.`);
    setEditing(null);
  }

  async function saveSkip(forbidden: boolean) {
    await run(
      async () => setLifecycle(await profileApi.setLifecycleSkip(orgId, profileId, forbidden)),
      { success: "Rule on skipping steps saved.", failure: "Could not save the rule on skipping steps." },
    );
  }

  async function saveWorkflow(workflowId: string, mode: StageWorkflowMode) {
    setWorkflow(await profileApi.setStageWorkflow(orgId, profileId, workflowId, mode));
  }

  async function removeWorkflow() {
    setRemoving(false);
    await run(
      async () => setWorkflow(await profileApi.clearStageWorkflow(orgId, profileId)),
      { success: "Required stage workflow removed.", failure: "Could not remove the required stage workflow." },
    );
  }

  if (failed && !lifecycle) return <LoadFailed message="The lifecycle policy could not be loaded." onRetry={() => void load()} />;
  if (!lifecycle || !workflow) return <Spinner />;

  return (
    <div className="stack">
      <section className="stack" aria-label="Required states">
        <h3 style={{ margin: 0 }}>Required states</h3>
        <PolicyTable
          ariaLabel="Required states by record type"
          rows={lifecycle.types}
          emptyText="No record type of this organisation has an optional state."
          columns={[{
            key: "required", label: "Required states", sortValue: (row) => requiredLabels(row).join(", "),
            render: (row) => {
              const labels = requiredLabels(row);
              return labels.length === 0 ? <span className="text-muted">None</span> : (
                <div className="row" style={{ gap: "var(--space-1)" }}>{labels.map((label) => <Badge key={label}>{label}</Badge>)}</div>
              );
            },
          }]}
          rowMenu={(row) => [{ label: "Edit required states", onSelect: () => setEditing(row) }]}
          rowMenuLabel={(row) => `Actions for ${row.label} required states`}
        />
      </section>

      <section className="stack" aria-label="Skipping steps">
        <CheckboxField
          label="Forbid skipping steps" checked={lifecycle.skip_forbidden} help={GOVERNANCE_HELP.lifecycleSkip}
          heading="Skipping steps" onChange={(forbidden) => void saveSkip(forbidden)}
        />
      </section>

      <section className="stack" aria-label="Required stage workflow">
        <h3 style={{ margin: 0 }}>Required stage workflow</h3>
        {workflow.options.length === 0 ? (
          <p className="text-muted">This organisation has no stage workflows. Define one before a profile can require it.</p>
        ) : (
          <>
            <div className="row" style={{ gap: "var(--space-2)" }}>
              <FieldCaption label="Current requirement" help={GOVERNANCE_HELP.stageWorkflow} />
              {workflow.workflow_id ? (
                <>
                  <Badge tone="accent">{workflow.workflow_name ?? ""}</Badge>
                  <span className="text-muted">{STAGE_WORKFLOW_MODE_LABEL[workflow.mode]}</span>
                </>
              ) : <span className="text-muted">None</span>}
            </div>
            <StageWorkflowForm
              key={`${workflow.workflow_id ?? ""}:${workflow.mode}`} workflow={workflow}
              onSave={saveWorkflow} onRemove={() => setRemoving(true)}
            />
          </>
        )}
      </section>

      {editing && (
        <LifecycleRequiredModal
          typeLabel={editing.label} states={editing.states} initial={editing.required}
          onSave={(required) => saveRequired(editing, required)} onClose={() => setEditing(null)}
        />
      )}
      {removing && (
        <ConfirmDialog
          title="Remove required stage workflow" confirmLabel="Remove" onCancel={() => setRemoving(false)} onConfirm={() => void removeWorkflow()}
          message="New stages of the projects this profile applies to no longer start in this workflow, and projects are no longer limited to it. Existing stages are not changed."
        />
      )}
    </div>
  );
}

/**
 * The settings group that chooses the required workflow and how it binds, saved together.
 *
 * @param workflow The profile's current stage workflow policy and the workflows to choose from.
 * @param onSave Saves the choice; rejects to report a failure beside the Save button.
 * @param onRemove Starts the confirmed removal; the control is drawn only while a workflow is required.
 */
function StageWorkflowForm({
  workflow, onSave, onRemove,
}: {
  workflow: ProfileStageWorkflow;
  onSave: (workflowId: string, mode: StageWorkflowMode) => Promise<void>;
  onRemove: () => void;
}) {
  const [workflowId, setWorkflowId] = useState(workflow.workflow_id ?? "");
  const [mode, setMode] = useState<StageWorkflowMode>(workflow.mode);
  const dirty = workflowId !== "" && (workflowId !== (workflow.workflow_id ?? "") || mode !== workflow.mode);

  return (
    <div className="stack">
      <SettingsForm dirty={dirty} onSave={() => onSave(workflowId, mode)} successMessage="Required stage workflow saved.">
        <LabeledSelect
          required label="Stage workflow" help={GOVERNANCE_HELP.stageWorkflow} value={workflowId} onChange={setWorkflowId}
          placeholder="Select a workflow" options={workflow.options.map((o) => ({ value: o.id, label: o.name }))}
        />
        <LabeledSelect
          label="How it binds projects" help={GOVERNANCE_HELP.stageWorkflowMode} value={mode} placeholder={null}
          onChange={(value) => setMode(value as StageWorkflowMode)} options={MODE_OPTIONS}
        />
      </SettingsForm>
      {workflow.workflow_id && (
        <button type="button" className="btn" style={{ alignSelf: "flex-start" }} onClick={onRemove}>Remove requirement</button>
      )}
    </div>
  );
}
