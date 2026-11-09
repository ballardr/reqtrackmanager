/**
 * Module: components/PhaseSchedulePanel
 *
 * Project administration of the phase schedule. The reminder lead time (days before a phase's expected start
 * that its reminder is sent) is set once for the project; each stage then lists the phases of its workflow
 * (or, when component phases are on, of a chosen component's track) with an expected range, the actual start and
 * completion, and a badge for the current phase and for one that is overdue. A stage's owner is the user or
 * group reminded; with none, the project managers are.
 *
 * Time shapes: the expected range is two calendar dates compared with the viewer's own day; the actual dates are
 * UTC instants shown in the viewer's timezone.
 */
import { Pencil } from "lucide-react";
import { useCallback, useState } from "react";

import { api } from "../api/client";
import type {
  Component, ComponentPhases, OrgUser, PhasePlan, PhasePlans, PrincipalRef, ProjectStage, StageWorkflow,
} from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useDisclosureState } from "../hooks/useDisclosureState";
import { useMutation } from "../hooks/useMutation";
import { localToday } from "../utils/localDate";
import { Badge } from "./Badge";
import { DisclosureRow } from "./DisclosureRow";
import { LabeledSelect } from "./LabeledSelect";
import { PhaseRangeEditor } from "./PhaseRangeEditor";
import { PrincipalFormField } from "./PrincipalFormField";

const INHERIT = "inherit";
const STAGE_SCOPE = "stage";
const USUAL_LEAD_DAYS = [0, 1, 2, 3, 5, 7, 10, 14, 21, 28, 30, 60, 90];

/** `YYYY-MM-DD` shown in the viewer's locale, without any timezone shift (a calendar date has none). */
function formatDay(day: string): string {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(year, month - 1, date).toLocaleDateString();
}

/** Whole calendar days from `expectedTo` (a date) to the local day `completedAt` falls on. */
function daysLate(expectedTo: string, completedAt: string): number {
  const [year, month, date] = expectedTo.split("-").map(Number);
  const done = new Date(completedAt);
  const doneDay = Date.UTC(done.getFullYear(), done.getMonth(), done.getDate());
  return Math.round((doneDay - Date.UTC(year, month - 1, date)) / 86_400_000);
}

/**
 * @param projectId The project being administered.
 * @param organizationId Its organisation (owner picker).
 * @param orgUsers The organisation's users (owner picker).
 * @param onChanged Called after any change, so a page showing stage state elsewhere can reload.
 */
export function PhaseSchedulePanel({
  projectId, organizationId, orgUsers, onChanged,
}: { projectId: string; organizationId: string; orgUsers: OrgUser[]; onChanged?: () => void }) {
  const strings = useStrings();
  const run = useMutation();
  const [plans, setPlans] = useState<PhasePlans | null>(null);
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [components, setComponents] = useState<Component[]>([]);
  const [workflows, setWorkflows] = useState<StageWorkflow[]>([]);
  const [tracks, setTracks] = useState<ComponentPhases | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [scopes, setScopes] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<{ stage: ProjectStage; componentId: string | null; phaseId: string; phaseName: string } | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const base = `/api/v1/projects/${projectId}`;
  // One stage is shown open; several start closed, each with its current phase on the row.
  const disclosure = useDisclosureState("phaseSchedule:stages", stages.length > 1);

  const reload = useCallback(async () => {
    try {
      const [planList, stageList, componentList, workflowList, trackList] = await Promise.all([
        api.get<PhasePlans>(`${base}/phase-plans`),
        api.get<ProjectStage[]>(`${base}/stages`),
        api.get<Component[]>(`${base}/components`),
        api.get<StageWorkflow[]>(`${base}/stage-workflows`),
        api.get<ComponentPhases>(`${base}/component-stages`),
      ]);
      setPlans(planList);
      setStages(stageList);
      setComponents(componentList);
      setWorkflows(workflowList);
      setTracks(trackList);
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, strings.phaseSchedule.loadFailed));
    }
  }, [base, strings.phaseSchedule.loadFailed]);

  useLoadOnChange(reload, [base]);

  async function setLeadDays(value: string) {
    const lead_days = value === INHERIT ? null : Number(value);
    if (await run(() => api.put(`${base}/phase-reminder-settings`, { lead_days }), "save", strings.phaseSchedule.nounLeadDays)) {
      await reload();
      onChanged?.();
    }
  }

  async function setOwner(stage: ProjectStage, owner: PrincipalRef | null) {
    if (await run(() => api.patch(`${base}/stages/${stage.id}`, { name: stage.name, owner }), "save", strings.phaseSchedule.nounOwner)) {
      await reload();
      onChanged?.();
    }
  }

  async function saveRange(expectedFrom: string | null, expectedTo: string | null) {
    if (!editing) return;
    setSaveError(null);
    try {
      await api.put(`${base}/stages/${editing.stage.id}/phase-plan`, {
        phase_id: editing.phaseId, component_id: editing.componentId, expected_from: expectedFrom, expected_to: expectedTo,
      });
    } catch (err) {
      setSaveError(toErrorMessage(err, strings.mutation.failure("save", strings.phaseSchedule.nounPlan)));
      return;
    }
    setEditing(null);
    await reload();
    onChanged?.();
  }

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (!plans) return null;
  const today = localToday();
  const leadOptions = Array.from(new Set([...USUAL_LEAD_DAYS, plans.lead_days])).sort((a, b) => a - b);
  const componentsOn = tracks?.mode === "on";
  return (
    <div className="stack">
      <LabeledSelect
        label={strings.phaseSchedule.leadDays} help={strings.help.phaseScheduleLeadDays} placeholder={null}
        value={plans.own_lead_days === null ? INHERIT : String(plans.own_lead_days)} onChange={(value) => void setLeadDays(value)}
        options={[
          ...leadOptions.map((days) => ({ value: String(days), label: strings.phaseSchedule.leadDaysOption(days) })),
          { value: INHERIT, label: strings.phaseSchedule.leadDaysInherit },
        ]}
      />
      {plans.own_lead_days === null && <div className="text-muted">{strings.phaseSchedule.inheritedNote(plans.lead_days)}</div>}
      {stages.length === 0 && <div className="text-muted">{strings.phaseSchedule.noStages}</div>}
      {stages.map((stage) => {
        const scope = componentsOn ? scopes[stage.id] ?? STAGE_SCOPE : STAGE_SCOPE;
        const componentId = scope === STAGE_SCOPE ? null : scope;
        const track = componentId ? tracks?.tracks.find((t) => t.component_id === componentId && t.stage_id === stage.id) : undefined;
        const workflowId = track ? track.workflow_id : stage.workflow_id;
        const currentPhaseId = track ? track.phase_id : stage.phase_id;
        const phases = workflows.find((w) => w.id === workflowId)?.phases ?? [];
        const rowFor = (phaseId: string): PhasePlan | undefined =>
          plans.plans.find((p) => p.stage_id === stage.id && p.component_id === componentId && p.phase_id === phaseId);
        return (
          <DisclosureRow
            key={stage.id} title={stage.name}
            summary={track?.not_applicable ? strings.componentPhases.notApplicableBadge : phases.find((p) => p.id === currentPhaseId)?.name}
            collapsed={disclosure.isCollapsed(stage.id)} onToggle={() => disclosure.toggle(stage.id)}
          >
            <PrincipalFormField
              label={strings.phaseSchedule.owner} help={strings.help.phaseScheduleOwner} ariaLabel={strings.phaseSchedule.ownerAria(stage.name)}
              orgUsers={orgUsers} organizationId={organizationId} projectId={projectId}
              value={stage.owner ? { type: stage.owner.type, id: stage.owner.id } : null} display={stage.owner}
              onChange={(owner) => void setOwner(stage, owner)} clearLabel={strings.phaseSchedule.unassign}
            />
            {componentsOn && (
              <LabeledSelect
                label={strings.phaseSchedule.scope} help={strings.help.phaseScheduleScope} placeholder={null} value={scope}
                onChange={(value) => setScopes((s) => ({ ...s, [stage.id]: value }))}
                options={[
                  { value: STAGE_SCOPE, label: strings.phaseSchedule.scopeStage },
                  ...components.map((c) => ({ value: c.id, label: c.name })),
                ]}
              />
            )}
            {track?.not_applicable ? (
              <Badge>{strings.componentPhases.notApplicableBadge}</Badge>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>{strings.phaseSchedule.phase}</th>
                    <th>{strings.phaseSchedule.expected}</th>
                    <th>{strings.phaseSchedule.actual}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {phases.map((phase) => {
                    const row = rowFor(phase.id);
                    const isCurrent = phase.id === currentPhaseId;
                    const overdue = isCurrent && phase.kind !== "closed" && !!row?.expected_to && row.expected_to < today;
                    const late = row?.expected_to && row.completed_at ? daysLate(row.expected_to, row.completed_at) : null;
                    return (
                      <tr key={phase.id}>
                        <td>
                          {phase.name}{" "}
                          {isCurrent && <Badge tone="info">{strings.phaseSchedule.currentBadge}</Badge>}{" "}
                          {overdue && <Badge tone="danger">{strings.phaseSchedule.overdueBadge}</Badge>}
                        </td>
                        <td>
                          {row?.expected_from || row?.expected_to
                            ? `${row.expected_from ? formatDay(row.expected_from) : "…"} – ${row.expected_to ? formatDay(row.expected_to) : "…"}`
                            : <span className="text-muted">{strings.phaseSchedule.notScheduled}</span>}
                        </td>
                        <td>
                          {row?.started_at && <div>{strings.phaseSchedule.started(new Date(row.started_at).toLocaleDateString())}</div>}
                          {row?.completed_at && (
                            <div>
                              {strings.phaseSchedule.completed(new Date(row.completed_at).toLocaleDateString())}
                              {late !== null && (
                                <> · {late > 0 ? strings.phaseSchedule.daysLate(late) : late < 0 ? strings.phaseSchedule.daysEarly(-late) : strings.phaseSchedule.onTime}</>
                              )}
                            </div>
                          )}
                        </td>
                        <td>
                          <button
                            className="btn" aria-label={strings.phaseSchedule.editPhase(phase.name)} title={strings.phaseSchedule.editPhase(phase.name)}
                            onClick={() => { setSaveError(null); setEditing({ stage, componentId, phaseId: phase.id, phaseName: phase.name }); }}
                          >
                            <Pencil />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </DisclosureRow>
        );
      })}
      {editing && (
        <PhaseRangeEditor
          title={strings.phaseSchedule.editTitle(editing.stage.name, editing.phaseName)}
          expectedFrom={rowOf(plans, editing)?.expected_from ?? null} expectedTo={rowOf(plans, editing)?.expected_to ?? null}
          error={saveError} onCancel={() => setEditing(null)} onSave={(from, to) => void saveRange(from, to)}
        />
      )}
    </div>
  );
}

function rowOf(plans: PhasePlans, editing: { stage: ProjectStage; componentId: string | null; phaseId: string }): PhasePlan | undefined {
  return plans.plans.find((p) => p.stage_id === editing.stage.id && p.component_id === editing.componentId && p.phase_id === editing.phaseId);
}
