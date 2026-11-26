/**
 * Module: modules/traceability/ProfileBaselineTab
 *
 * The Baseline tab of a governance profile: the checks the profile enables before baselines, the kinds of baseline they
 * run before, whether project managers are told of a refusal and the fields a record must have filled.
 *
 * Responsibilities:
 * - Read the profile's baseline policy and edit it as one settings group with one Save (`SettingsForm`).
 * - Offer required-field choices from one project of the organisation, because a type's custom fields differ between
 *   projects; a required field that project does not offer still shows under its key and can be removed.
 * - Show an empty state when the organisation has no baseline check to enable.
 *
 * Dependencies: `profileApi`, `BaselineSettingsFields`, `loadOrgProjects`.
 */
import { useCallback, useEffect, useState } from "react";

import { loadOrgProjects } from "../../api/lifecycles";
import { LabeledSelect } from "../../components/LabeledSelect";
import { LoadFailed } from "../../components/LoadFailed";
import { SettingsForm } from "../../components/SettingsForm";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage } from "../../context/ToastContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { profileApi } from "./api";
import { BaselineSettingsFields } from "./BaselineSettingsFields";
import { GOVERNANCE_HELP } from "./help";
import { baselineProblem, sameBaseline } from "./policyText";
import type { BaselineFieldOption, BaselineSettings, ProfileBaseline } from "./types";

/**
 * @param orgId The organisation that owns the profile.
 * @param profileId The profile whose baseline policy is edited.
 */
export function ProfileBaselineTab({ orgId, profileId }: { orgId: string; profileId: string }) {
  const [data, setData] = useState<ProfileBaseline | null>(null);
  const [draft, setDraft] = useState<BaselineSettings | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [projectId, setProjectId] = useState("");
  const [fieldOptions, setFieldOptions] = useState<Record<string, BaselineFieldOption[]>>({});
  const [fieldsFailed, setFieldsFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const loaded = await profileApi.baseline(orgId, profileId);
      setData(loaded);
      setDraft(loaded.settings);
      setFailure(null);
    } catch (err) {
      setFailure(toErrorMessage(err, "The baseline policy could not be loaded."));
    }
  }, [orgId, profileId]);
  useLoadOnChange(load, [orgId, profileId]);

  useEffect(() => {
    let live = true;
    loadOrgProjects(orgId).then(
      (loaded) => {
        if (!live) return;
        setProjects(loaded.map((p) => ({ id: p.id, name: p.name })));
        setProjectId((current) => current || loaded[0]?.id || "");
      },
      () => { if (live) setProjects([]); },
    );
    return () => { live = false; };
  }, [orgId]);

  useEffect(() => {
    if (!projectId) return;
    let live = true;
    profileApi.baselineFields(orgId, profileId, projectId).then(
      (fields) => { if (live) { setFieldOptions(fields.types); setFieldsFailed(false); } },
      () => { if (live) { setFieldOptions({}); setFieldsFailed(true); } },
    );
    return () => { live = false; };
  }, [orgId, profileId, projectId]);

  async function save() {
    if (!draft) return;
    const next = await profileApi.setBaseline(orgId, profileId, draft);
    setData(next);
    setDraft(next.settings);
  }

  if (failure && !data) return <LoadFailed message={failure} onRetry={() => void load()} />;
  if (!data || !draft) return <Spinner />;
  if (data.check_options.length === 0) return <p className="text-muted">No baseline checks are available for this organisation.</p>;

  return (
    <SettingsForm dirty={!sameBaseline(draft, data.settings) && baselineProblem(draft) === null} onSave={save} successMessage="Baseline policy saved.">
      <BaselineSettingsFields
        settings={draft} onChange={setDraft} checkOptions={data.check_options} types={data.types} fieldOptions={fieldOptions}
        fieldsSlot={(
          <>
            <LabeledSelect
              label="Project for field choices" help={GOVERNANCE_HELP.baselineFieldsProject} value={projectId} onChange={setProjectId}
              placeholder={null} options={projects.map((p) => ({ value: p.id, label: p.name }))}
            />
            {fieldsFailed && <p className="text-muted" role="alert">The fields of this project could not be loaded.</p>}
          </>
        )}
      />
    </SettingsForm>
  );
}
