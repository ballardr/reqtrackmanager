/**
 * Module: modules/traceability/OrgHealthDefaultsPanel
 *
 * The Governance health section of Organisation Administration: the way every project of the organisation keeps its
 * governance health unless the project chooses its own (on demand, a snapshot at an interval or a snapshot on change, and
 * the interval).
 *
 * Responsibilities:
 * - Read and save the organisation's default (`healthDefaultApi`) as one settings group with a single Save.
 * - Offer the interval only for the mode that uses it, and keep the stored interval unchanged for the other modes.
 *
 * Design decisions: the mode and interval are options of closed vocabularies, drawn through the label maps; what each mode
 * means is in the field's `(?)` help, not in the layout.
 *
 * Dependencies: `healthDefaultApi`, `SettingsForm`, `LabeledSelect`.
 */
import { useCallback, useState } from "react";

import { LabeledSelect } from "../../components/LabeledSelect";
import { LoadFailed } from "../../components/LoadFailed";
import { SettingsForm } from "../../components/SettingsForm";
import { Spinner } from "../../components/Spinner";
import { useStrings } from "../../context/TerminologyContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { healthDefaultApi } from "./api";
import { GOVERNANCE_HELP } from "./help";
import { HEALTH_MODE_LABEL, healthIntervalLabel, type HealthDefault, type HealthMode } from "./types";

const MODE_OPTIONS = (Object.keys(HEALTH_MODE_LABEL) as HealthMode[]).map((mode) => ({ value: mode, label: HEALTH_MODE_LABEL[mode] }));

/**
 * @param orgId The organisation whose default is edited.
 */
export function OrgHealthDefaultsPanel({ orgId }: { orgId: string }) {
  const strings = useStrings();
  const [saved, setSaved] = useState<HealthDefault | null>(null);
  const [mode, setMode] = useState<HealthMode>("on_demand");
  const [interval, setInterval] = useState(24);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const loaded = await healthDefaultApi.get(orgId);
      setSaved(loaded);
      setMode(loaded.mode);
      setInterval(loaded.interval_hours);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [orgId]);
  useLoadOnChange(load, [orgId]);

  if (failed && !saved) {
    return <LoadFailed message={strings.requestFailure.loadFailed("The governance health default")} onRetry={() => { setFailed(false); void load(); }} />;
  }
  if (!saved) return <Spinner />;

  const usesInterval = mode === "snapshot_interval";
  const dirty = mode !== saved.mode || (usesInterval && interval !== saved.interval_hours);

  async function save() {
    const updated = await healthDefaultApi.set(orgId, mode, usesInterval ? interval : saved?.interval_hours ?? interval);
    setSaved(updated);
    setMode(updated.mode);
    setInterval(updated.interval_hours);
  }

  return (
    <SettingsForm dirty={dirty} onSave={save} successMessage="The governance health default is saved.">
      <LabeledSelect
        label="Default mode" help={GOVERNANCE_HELP.healthMode} placeholder={null}
        value={mode} onChange={(value) => setMode(value as HealthMode)} options={MODE_OPTIONS} autoWidth
      />
      {usesInterval && (
        <LabeledSelect
          label="Default snapshot interval" help={GOVERNANCE_HELP.healthInterval} placeholder={null}
          value={String(interval)} onChange={(value) => setInterval(Number(value))}
          options={saved.interval_options.map((hours) => ({ value: String(hours), label: healthIntervalLabel(hours) }))} autoWidth
        />
      )}
    </SettingsForm>
  );
}
