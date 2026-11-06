/**
 * Module: modules/context_strategy/PainPointSubmissionPanel
 *
 * Who may submit a Pain Point, on Project Admin and Organisation Admin: Pain Point Managers only (the platform
 * default) or any project member. A project chooses its own value or inherits (its parent project's,
 * else the organisation's default, else Pain Point Managers only); the organisation sets the default for projects that
 * choose nothing. The setting saves on change and confirms with a toast; changing it is for someone who manages
 * the project or the organisation, which the server enforces. Editing and triage are manager-tier whichever is
 * chosen.
 */
import { useState } from "react";

import { LabeledSelect } from "../../components/LabeledSelect";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { orgPainPointSettingsApi, projectPainPointApi } from "./api";
import { CONTEXT_STRATEGY_HELP } from "./help";
import {
  PAIN_POINT_SUBMISSION_POLICY_LABEL,
  PAIN_POINT_SUBMISSION_SOURCE_LABEL,
  type OrgPainPointSubmissionSettings,
  type PainPointSubmissionPolicy,
  type PainPointSubmissionSettings,
} from "./types";

const POLICY_OPTIONS = Object.entries(PAIN_POINT_SUBMISSION_POLICY_LABEL).map(([value, label]) => ({ value, label }));

/** The `<select>` value meaning "no setting of its own". */
const INHERIT = "";

/** @param projectId The project whose setting this edits. */
export function ProjectPainPointSubmissionPanel({ projectId }: { projectId: string }) {
  const { showToast } = useToast();
  const [settings, setSettings] = useState<PainPointSubmissionSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useLoadOnChange(async () => {
    try {
      setSettings(await projectPainPointApi.getSubmissionSettings(projectId));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "Could not load the Pain Point submission setting."));
    }
  }, [projectId]);

  async function change(value: string) {
    try {
      const policy = value === INHERIT ? null : (value as PainPointSubmissionPolicy);
      setSettings(await projectPainPointApi.setSubmissionPolicy(projectId, policy));
      showToast("Submission setting saved.");
    } catch (err) {
      showToast(toErrorMessage(err, "Could not save the submission setting."), "error");
    }
  }

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (settings === null) return <Spinner />;
  return (
    <div className="stack">
      <LabeledSelect
        help={CONTEXT_STRATEGY_HELP.painPointSubmissionProject}
        label="Who can submit a Pain Point"
        value={settings.own_policy ?? INHERIT}
        placeholder={null}
        onChange={(value) => void change(value)}
        options={[{ value: INHERIT, label: "Inherit" }, ...POLICY_OPTIONS]}
      />
      {settings.own_policy === null && (
        <p className="text-muted" data-testid="pain-point-submission-inherited">
          Inherited from {PAIN_POINT_SUBMISSION_SOURCE_LABEL[settings.source]}:{" "}
          {PAIN_POINT_SUBMISSION_POLICY_LABEL[settings.submission_policy]}.
        </p>
      )}
    </div>
  );
}

/** @param orgId The organisation whose default this edits. */
export function OrgPainPointSubmissionPanel({ orgId }: { orgId: string }) {
  const { showToast } = useToast();
  const [settings, setSettings] = useState<OrgPainPointSubmissionSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useLoadOnChange(async () => {
    try {
      setSettings(await orgPainPointSettingsApi.get(orgId));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "Could not load the Pain Point submission setting."));
    }
  }, [orgId]);

  async function change(value: string) {
    try {
      const policy = value === INHERIT ? null : (value as PainPointSubmissionPolicy);
      setSettings(await orgPainPointSettingsApi.setSubmissionPolicy(orgId, policy));
      showToast("Submission default saved.");
    } catch (err) {
      showToast(toErrorMessage(err, "Could not save the submission default."), "error");
    }
  }

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (settings === null) return <Spinner />;
  return (
    <LabeledSelect
      help={CONTEXT_STRATEGY_HELP.painPointSubmission}
      label="Who can submit a Pain Point by default"
      value={settings.submission_policy ?? INHERIT}
      placeholder={null}
      onChange={(value) => void change(value)}
      options={[{ value: INHERIT, label: "Not set (Pain Point Managers only)" }, ...POLICY_OPTIONS]}
    />
  );
}
