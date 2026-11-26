/**
 * Module: modules/traceability/ProjectHealthSettingsPanel
 *
 * The Governance health section of Project Administration: how this project keeps its governance health (the mode, the
 * snapshot interval) and which person runs the baseline checks of a snapshot.
 *
 * Responsibilities:
 * - Read the project's settings with where each value in force comes from (`projectGovernanceApi.healthSettings`) and
 *   save the project's own three choices as one settings group with a single Save.
 * - Let each of the mode and the interval follow the organisation's default, shown as the first option with the default
 *   it would give, and name the tier each value in force comes from.
 * - Choose the runner from the organisation's users; a runner who can no longer run the checks is flagged inline.
 * - Show the settings read-only to a person who cannot manage the project's governance.
 *
 * Design decisions: the size guidance for the on-demand mode is part of the mode field's `(?)` help, composed from the
 * API's limit, so it is never permanent text. The interval field appears only while the mode in effect is a snapshot at an
 * interval, and an interval already chosen is kept when the mode changes.
 *
 * Dependencies: `projectGovernanceApi`, `useProjectPeople`, `SettingsForm`, `LabeledSelect`, `UserAutocomplete`.
 */
import { useCallback, useState } from "react";

import { Badge } from "../../components/Badge";
import { FieldCaption } from "../../components/FieldHelp";
import { InlineMessage } from "../../components/InlineMessage";
import { LabeledSelect } from "../../components/LabeledSelect";
import { LoadFailed } from "../../components/LoadFailed";
import { RemovableChip } from "../../components/RemovableChip";
import { SettingsForm } from "../../components/SettingsForm";
import { Spinner } from "../../components/Spinner";
import { UserAutocomplete } from "../../components/UserAutocomplete";
import { useStrings } from "../../context/TerminologyContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useProjectPeople } from "../../hooks/useProjectPeople";
import { projectGovernanceApi } from "./api";
import { GOVERNANCE_HELP } from "./help";
import {
  HEALTH_MODE_LABEL,
  HEALTH_SETTING_SOURCE_LABEL,
  healthIntervalLabel,
  type HealthMode,
  type HealthSettings,
} from "./types";

const MODE_OPTIONS = (Object.keys(HEALTH_MODE_LABEL) as HealthMode[]).map((mode) => ({ value: mode, label: HEALTH_MODE_LABEL[mode] }));

/** The mode field's help: the mode descriptions and, in one more line, when a snapshot mode is advised. */
function modeHelp(limit: number): string {
  return `${GOVERNANCE_HELP.healthMode}\nOn demand stays fast at any size while no baseline check is enabled; with checks enabled, a snapshot mode is advised above ${limit.toLocaleString()} records.`;
}

/**
 * @param projectId The project whose settings are edited.
 */
export function ProjectHealthSettingsPanel({ projectId }: { projectId: string }) {
  const strings = useStrings();
  const { orgUsers } = useProjectPeople(projectId);
  const [saved, setSaved] = useState<HealthSettings | null>(null);
  const [failed, setFailed] = useState(false);
  const [mode, setMode] = useState<HealthMode | null>(null);
  const [interval, setInterval] = useState<number | null>(null);
  const [runnerId, setRunnerId] = useState<string | null>(null);

  const apply = useCallback((settings: HealthSettings) => {
    setSaved(settings);
    setMode(settings.own_mode);
    setInterval(settings.own_interval_hours);
    setRunnerId(settings.checks_runner?.id ?? null);
  }, []);

  const load = useCallback(async () => {
    try {
      apply(await projectGovernanceApi.healthSettings(projectId));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [projectId, apply]);
  useLoadOnChange(load, [projectId]);

  if (failed && !saved) {
    return <LoadFailed message={strings.requestFailure.loadFailed("The governance health settings")} onRetry={() => { setFailed(false); void load(); }} />;
  }
  if (!saved) return <Spinner />;

  const canManage = saved.can_manage;
  const effectiveMode = mode ?? saved.organization_mode;
  const dirty = mode !== saved.own_mode || interval !== saved.own_interval_hours || runnerId !== (saved.checks_runner?.id ?? null);
  const runnerName = runnerId === null
    ? null
    : saved.checks_runner?.id === runnerId
      ? saved.checks_runner.name
      : orgUsers?.find((user) => user.user_id === runnerId)?.display_name ?? "Selected person";
  const runnerChanged = runnerId !== (saved.checks_runner?.id ?? null);

  async function save() {
    apply(await projectGovernanceApi.setHealthSettings(projectId, { mode, interval_hours: interval, checks_runner_id: runnerId }));
  }

  return (
    <SettingsForm dirty={dirty && canManage} onSave={save} successMessage="The governance health settings are saved.">
      <div className="row" style={{ alignItems: "flex-end" }}>
        <LabeledSelect
          label="Mode" help={modeHelp(saved.on_demand_record_limit)} disabled={!canManage}
          placeholder={`Organisation default (${HEALTH_MODE_LABEL[saved.organization_mode]})`}
          value={mode ?? ""} onChange={(value) => setMode(value === "" ? null : (value as HealthMode))}
          options={MODE_OPTIONS} autoWidth
        />
        <Badge>{HEALTH_SETTING_SOURCE_LABEL[saved.mode_source]}</Badge>
      </div>
      {effectiveMode === "snapshot_interval" && (
        <div className="row" style={{ alignItems: "flex-end" }}>
          <LabeledSelect
            label="Snapshot interval" help={GOVERNANCE_HELP.healthInterval} disabled={!canManage}
            placeholder={`Organisation default (${healthIntervalLabel(saved.organization_interval_hours)})`}
            value={interval === null ? "" : String(interval)} onChange={(value) => setInterval(value === "" ? null : Number(value))}
            options={saved.interval_options.map((hours) => ({ value: String(hours), label: healthIntervalLabel(hours) }))} autoWidth
          />
          <Badge>{HEALTH_SETTING_SOURCE_LABEL[saved.interval_source]}</Badge>
        </div>
      )}
      <div className="stack" style={{ gap: "var(--space-1)" }}>
        <FieldCaption label="Baseline check runner" help={GOVERNANCE_HELP.healthRunner} />
        {runnerName !== null ? (
          <div>
            <RemovableChip
              label={runnerName} removeLabel="Remove the baseline check runner"
              onRemove={canManage ? () => setRunnerId(null) : undefined}
            />
          </div>
        ) : canManage ? (
          <UserAutocomplete
            users={(orgUsers ?? []).filter((user) => user.is_active && !user.is_archived)}
            onSelect={setRunnerId} ariaLabel="Baseline check runner" placeholder="Search for a person"
          />
        ) : (
          <span className="text-muted">No runner is set.</span>
        )}
        {!runnerChanged && <InlineMessage tone="warning">{saved.runner_problem}</InlineMessage>}
      </div>
    </SettingsForm>
  );
}
