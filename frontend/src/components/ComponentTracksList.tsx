/**
 * Module: components/ComponentTracksList
 *
 * Every component's track through the stages when component phases are on, with a phase picker for each: the list shared by
 * project administration (where it also edits a track) and the "Stage phases" page (where a track's owner moves theirs).
 *
 * Responsibilities:
 * - Show one collapsible group per component, summarised by its current phases, so a project with many components and
 *   stages stays readable; filter by stage and by "tracks I can move".
 * - Move a track (a closed phase first asks whether to complete the component's approved requirements too) and report it
 *   through `onChanged`; the server decides who may move (`can_move`), this list only disables the picker.
 *
 * Design decisions: a locked-phase move by a person who cannot make it is not offered as a choice; the server enforces it
 * regardless. Editing a track (workflow, applicability, owner) is offered only where the host passes `onEdit`.
 */
import { ChevronDown, ChevronRight, Pencil } from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "../api/client";
import type { Component, ComponentPhases, ComponentTrack, ProjectStage, StageWorkflow } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { useMutation } from "../hooks/useMutation";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { CheckboxField } from "./FormFields";
import { FilterSelect } from "./FilterSelect";
import { InlineSelect } from "./LabeledSelect";
import { PrincipalBadge } from "./PrincipalBadge";

/**
 * @param projectId The project.
 * @param state The component-phases state (its tracks).
 * @param stages The project's stages, in order.
 * @param components The project's components.
 * @param workflows The workflows the project may use (each track's phases come from its workflow).
 * @param onChanged Called after a move, so the host reloads.
 * @param onEdit Opens the host's track editor; omit it where the person cannot edit a track.
 */
export function ComponentTracksList({
  projectId, state, stages, components, workflows, onChanged, onEdit,
}: {
  projectId: string;
  state: ComponentPhases;
  stages: ProjectStage[];
  components: Component[];
  workflows: StageWorkflow[];
  onChanged: () => void;
  onEdit?: (track: ComponentTrack) => void;
}) {
  const strings = useStrings();
  const t = strings.componentPhases;
  const run = useMutation();
  const [stageFilter, setStageFilter] = useState("");
  const [movableOnly, setMovableOnly] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [closing, setClosing] = useState<{ track: ComponentTrack; phaseId: string; phaseName: string } | null>(null);
  const [cascade, setCascade] = useState(false);
  const base = `/api/v1/projects/${projectId}`;

  const tracksOf = useMemo(() => {
    const map = new Map<string, ComponentTrack[]>();
    for (const track of state.tracks) {
      if (stageFilter && track.stage_id !== stageFilter) continue;
      if (movableOnly && !track.can_move) continue;
      map.set(track.component_id, [...(map.get(track.component_id) ?? []), track]);
    }
    return map;
  }, [state.tracks, stageFilter, movableOnly]);

  async function move(track: ComponentTrack, phaseId: string, cascadeToRequirements: boolean) {
    const path = `${base}/components/${track.component_id}/stages/${track.stage_id}/transition`;
    if (await run(() => api.post(path, { phase_id: phaseId, cascade_to_requirements: cascadeToRequirements }), "save", t.nounSingular)) {
      onChanged();
    }
  }

  function requestMove(track: ComponentTrack, phaseId: string) {
    const phase = workflows.find((w) => w.id === track.workflow_id)?.phases.find((p) => p.id === phaseId);
    if (phase?.kind === "closed") {
      setCascade(false);
      setClosing({ track, phaseId, phaseName: phase.name });
    } else {
      void move(track, phaseId, false);
    }
  }

  const toggle = (id: string) => setCollapsed((current) => {
    const next = new Set(current);
    if (!next.delete(id)) next.add(id);
    return next;
  });
  const shown = components.filter((c) => (tracksOf.get(c.id) ?? []).length > 0);

  return (
    <div className="stack">
      <div className="row" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
        <FilterSelect
          label={t.filterStage} help={t.filterStageHelp} value={stageFilter} onChange={setStageFilter} allLabel={t.allStages}
          options={stages.map((s) => ({ value: s.id, label: s.name }))}
        />
        <CheckboxField help={t.movableOnlyHelp} label={t.movableOnly} checked={movableOnly} onChange={setMovableOnly} />
      </div>
      {shown.length === 0 && <div className="text-muted">{movableOnly ? t.noMovable : t.noTracks}</div>}
      {shown.map((component) => {
        const tracks = tracksOf.get(component.id) ?? [];
        const open = !collapsed.has(component.id);
        return (
          <div key={component.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "var(--space-3)" }}>
            <button
              type="button" className="btn" style={{ alignSelf: "flex-start" }} aria-expanded={open}
              onClick={() => toggle(component.id)} aria-label={t.toggleComponent(component.name)}
            >
              {open ? <ChevronDown /> : <ChevronRight />} <strong>{component.name}</strong>
              {!open && (
                <span className="text-muted">
                  {tracks.map((tr) => `${stages.find((s) => s.id === tr.stage_id)?.name ?? ""}: ${tr.not_applicable ? t.notApplicableBadge : tr.phase_name}`).join(" · ")}
                </span>
              )}
            </button>
            {open && tracks.map((track) => {
              const stage = stages.find((s) => s.id === track.stage_id);
              if (!stage) return null;
              const phases = workflows.find((w) => w.id === track.workflow_id)?.phases ?? [{ id: track.phase_id, name: track.phase_name, kind: track.phase_kind }];
              return (
                <div key={stage.id} className="row" style={{ justifyContent: "space-between" }}>
                  <div className="row">
                    <span style={{ minWidth: "10rem" }}>{stage.name}</span>
                    {track.not_applicable ? (
                      <Badge>{t.notApplicableBadge}</Badge>
                    ) : (
                      <InlineSelect
                        ariaLabel={t.track(component.name, stage.name)} value={track.phase_id} placeholder={null}
                        maxWidth={220} disabled={!track.can_move} onChange={(next) => requestMove(track, next)}
                        options={phases.map((p) => ({ value: p.id, label: p.name }))}
                      />
                    )}
                    {track.customised && <Badge>{track.workflow_name}</Badge>}
                    {track.previous_closed && <Badge tone="info">{t.previousClosedBadge}</Badge>}
                  </div>
                  <div className="row">
                    <PrincipalBadge principal={track.owner} placeholder="" />
                    {onEdit && (
                      <button
                        className="btn" aria-label={t.editTrack(component.name, stage.name)} title={t.editTrack(component.name, stage.name)}
                        onClick={() => onEdit(track)}
                      >
                        <Pencil />
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        );
      })}
      {closing && (
        <ConfirmDialog
          title={t.completeStage}
          message={<CheckboxField help={strings.help.cascadeToRequirementsComponent} label={t.cascadeToRequirements} checked={cascade} onChange={setCascade} />}
          confirmLabel={closing.phaseName}
          onConfirm={() => {
            const { track, phaseId } = closing;
            setClosing(null);
            void move(track, phaseId, cascade);
          }}
          onCancel={() => setClosing(null)}
        />
      )}
    </div>
  );
}
