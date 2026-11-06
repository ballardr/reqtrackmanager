/**
 * Module: modules/product_feedback/SubmissionPolicyPanel
 *
 * The project's Product Feedback settings on Project Admin: who may submit a request, any project member (the
 * default) or triagers only (triagers can always edit, merge and decide requests whichever is chosen), and the
 * default order of the sections on a request's page (a person can still arrange their own). Each setting saves on
 * change and confirms with a toast; changing them is for someone who manages the project.
 */
import { useState } from "react";

import { FieldCaption } from "../../components/FieldHelp";
import { LabeledSelect } from "../../components/LabeledSelect";
import { SectionOrderEditor } from "../../components/SectionOrderEditor";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { applySectionOrder } from "../../utils/sectionOrder";
import { projectRequestApi } from "./api";
import { PRODUCT_FEEDBACK_HELP } from "./help";
import { REQUEST_PAGE_SECTIONS, REQUEST_SECTION_KEYS } from "./requestSections";
import { SUBMISSION_POLICY_LABEL, type SubmissionPolicy } from "./types";

/** @param projectId The project whose setting this edits. */
export function SubmissionPolicyPanel({ projectId }: { projectId: string }) {
  const { showToast } = useToast();
  const [policy, setPolicy] = useState<SubmissionPolicy | null>(null);
  const [sections, setSections] = useState<string[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useLoadOnChange(async () => {
    try {
      const settings = await projectRequestApi.getSettings(projectId);
      setPolicy(settings.submission_policy);
      setSections(settings.request_page_sections);
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

  async function changeSections(next: string[] | null) {
    try {
      setSections((await projectRequestApi.setRequestPageSections(projectId, next)).request_page_sections);
      showToast(next ? "Section order saved." : "Section order reset.");
    } catch (err) {
      showToast(toErrorMessage(err, "Could not save the section order."), "error");
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
      <div className="stack" style={{ gap: "var(--space-1)" }}>
        <FieldCaption label="Order of the sections on a request's page" help={PRODUCT_FEEDBACK_HELP.requestPageSections} muted />
        <SectionOrderEditor
          sections={REQUEST_PAGE_SECTIONS} order={applySectionOrder(REQUEST_SECTION_KEYS, sections)}
          onChange={(next) => void changeSections(next)} onReset={() => void changeSections(null)}
          resetLabel="Use the built-in order" resetDisabled={sections === null} ariaLabel="Request page section order"
        />
      </div>
    </div>
  );
}
