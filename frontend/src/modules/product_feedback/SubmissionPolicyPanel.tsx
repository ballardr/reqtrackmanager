/**
 * Module: modules/product_feedback/SubmissionPolicyPanel
 *
 * The project's Product Feedback setting on Project Admin: who may submit a request, any project member (the
 * default) or triagers only. Triagers can always edit, merge and decide requests whichever is chosen. The setting
 * saves on change and confirms with a toast; changing it is for someone who manages the project.
 */
import { useState } from "react";

import { LabeledSelect } from "../../components/LabeledSelect";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { projectRequestApi } from "./api";
import { PRODUCT_FEEDBACK_HELP } from "./help";
import { SUBMISSION_POLICY_LABEL, type SubmissionPolicy } from "./types";

/** @param projectId The project whose setting this edits. */
export function SubmissionPolicyPanel({ projectId }: { projectId: string }) {
  const { showToast } = useToast();
  const [policy, setPolicy] = useState<SubmissionPolicy | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useLoadOnChange(async () => {
    try {
      setPolicy((await projectRequestApi.getSettings(projectId)).submission_policy);
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "Could not load the Product Feedback settings."));
    }
  }, [projectId]);

  async function change(next: SubmissionPolicy) {
    try {
      setPolicy((await projectRequestApi.setSubmissionPolicy(projectId, next)).submission_policy);
      showToast("Submission setting saved.");
    } catch (err) {
      showToast(toErrorMessage(err, "Could not save the submission setting."), "error");
    }
  }

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (policy === null) return <Spinner />;
  return (
    <div className="stack">
      <LabeledSelect
        help={PRODUCT_FEEDBACK_HELP.submissionPolicy} label="Who can submit a request" value={policy} placeholder={null}
        onChange={(next) => void change(next as SubmissionPolicy)}
        options={Object.entries(SUBMISSION_POLICY_LABEL).map(([value, label]) => ({ value, label }))}
      />
    </div>
  );
}
