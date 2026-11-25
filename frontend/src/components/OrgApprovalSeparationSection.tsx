/**
 * Module: components/OrgApprovalSeparationSection
 *
 * The Approval section of the organisation Lifecycles group: for each record type with an approval step, whether every
 * project needs a separate approver, and the projects exempt from the requirement.
 *
 * Responsibilities:
 * - Read the organisation's rules and save them: one type's requirement and its exemptions (`ApprovalSeparationApi`);
 *   `api` and `loadProjects` are injectable for stories.
 * - Offer an exemption through the shared dialog, only for a type that is required (an exemption of a rule that is not
 *   in force has nothing to lift).
 *
 * Design decisions: "Project decides" keeps each project's own choice and the default (the creator may approve); the
 * requirement beats a project's stored choice without deleting it, so lifting the requirement restores the choice.
 */
import { useCallback, useState } from "react";

import {
  approvalSeparationApi, type ApprovalSeparationApi, type OrgSeparation,
} from "../api/approvalSeparation";
import { loadOrgProjects, type LoadOrgProjects } from "../api/lifecycles";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { LabeledSelect } from "./LabeledSelect";
import { ExemptionDialog, ExemptionList } from "./LifecycleExemptions";
import { Spinner } from "./Spinner";

/**
 * @param organizationId The organisation whose rules are configured.
 * @param api The calls (the live ones by default).
 * @param loadProjects Lists the organisation's projects for the exemption dialog (the live call by default).
 */
export function OrgApprovalSeparationSection({
  organizationId, api = approvalSeparationApi, loadProjects = loadOrgProjects,
}: { organizationId: string; api?: ApprovalSeparationApi; loadProjects?: LoadOrgProjects }) {
  const strings = useStrings();
  const text = strings.approvalSeparation;
  const lifecycleText = strings.lifecycleSettings;
  const { showToast } = useToast();
  const [types, setTypes] = useState<OrgSeparation[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [exempting, setExempting] = useState<OrgSeparation | null>(null);

  const load = useCallback(async () => {
    try {
      setTypes(await api.organization(organizationId));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [api, organizationId]);
  useLoadOnChange(load, [api, organizationId]);

  /** Runs a change, shows its outcome and reports whether it succeeded. */
  async function run(action: () => Promise<OrgSeparation[]>, message: string): Promise<boolean> {
    try {
      setTypes(await action());
      showToast(message);
      return true;
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
      return false;
    }
  }

  if (failed && !types) return <p className="text-muted" role="alert">{text.loadFailed}</p>;
  if (!types) return <Spinner />;
  const options = [
    { value: "decides", label: text.projectDecides },
    { value: "required", label: text.requiredEverywhere },
  ];

  return (
    <section className="stack" aria-label={text.heading}>
      <h3 style={{ margin: 0 }}>{text.heading}</h3>
      {types.length === 0 && <p className="text-muted">{text.noTypes}</p>}
      {types.map((type) => (
        <div key={type.artefact_type} className="stack" role="group" aria-label={text.fieldLabel(type.label)}>
          <LabeledSelect
            label={text.fieldLabel(type.label)} help={strings.help.approvalSeparationOrganization} placeholder={null} autoWidth
            value={type.required ? "required" : "decides"} options={options}
            onChange={(value) => void run(() => api.setRequired(organizationId, type.artefact_type, value === "required"), text.saved)}
          />
          {type.required && (
            <ExemptionList
              exemptions={type.exemptions} onAdd={() => setExempting(type)}
              onRemove={(projectId) => void run(() => api.removeExemption(organizationId, type.artefact_type, projectId), lifecycleText.exemptionRemoved)}
            />
          )}
        </div>
      ))}
      {exempting && (
        <ExemptionDialog
          title={text.exemptTitle(exempting.label)} taken={new Set(exempting.exemptions.map((e) => e.project_id))}
          organizationId={organizationId} loadProjects={loadProjects} onClose={() => setExempting(null)}
          onSave={(projectId, includeChildren) =>
            run(() => api.addExemption(organizationId, exempting.artefact_type, projectId, includeChildren), lifecycleText.exemptionAdded)}
        />
      )}
    </section>
  );
}
