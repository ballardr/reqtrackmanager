/**
 * Module: components/ProjectCodePolicyPanel
 *
 * Org Admin form for how project codes are formed (kind, length, automatic or manual
 * assignment) and whether a record code always shows its project code. The policy applies to
 * codes created from now on; existing codes are never rewritten.
 *
 * Dependencies: `PUT /api/v1/orgs/{id}/code-policy`.
 */
import { useState } from "react";

import { api } from "../api/client";
import {
  PROJECT_CODE_ASSIGNMENT_LABEL,
  PROJECT_CODE_KIND_LABEL,
  type Organization,
  type ProjectCodeAssignment,
  type ProjectCodeKind,
} from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { describeCodePolicy } from "../utils/codePolicy";
import { CheckboxField, TextField } from "./FormFields";
import { FormGrid } from "./FormGrid";
import { LabeledSelect } from "./LabeledSelect";

/**
 * @param org The organisation whose policy is edited.
 * @param onSaved Called with the saved organisation so the page can refresh its copy.
 */
export function ProjectCodePolicyPanel({ org, onSaved }: { org: Organization; onSaved: (org: Organization) => void }) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [kind, setKind] = useState<ProjectCodeKind>(org.project_code_policy.kind);
  const [minLength, setMinLength] = useState(String(org.project_code_policy.min_length));
  const [maxLength, setMaxLength] = useState(String(org.project_code_policy.max_length));
  const [assignment, setAssignment] = useState<ProjectCodeAssignment>(org.project_code_policy.assignment);
  const [enforce, setEnforce] = useState(org.enforce_code_everywhere);
  const [saving, setSaving] = useState(false);

  const min = Number(minLength);
  const max = Number(maxLength);
  const valid = Number.isInteger(min) && Number.isInteger(max) && min >= 1 && max >= min && max <= 10;

  async function save() {
    setSaving(true);
    try {
      const saved = await api.put<Organization>(`/api/v1/orgs/${org.id}/code-policy`, {
        kind, min_length: min, max_length: max, assignment, enforce_code_everywhere: enforce,
      });
      showToast(strings.orgAdmin.codePolicySaved);
      onSaved(saved);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>{strings.orgAdmin.codePolicyHint}</p>
      <FormGrid minColumn="10rem">
        <LabeledSelect
          label={strings.orgAdmin.codeKind}
          value={kind}
          onChange={(next) => setKind(next as ProjectCodeKind)}
          options={(Object.keys(PROJECT_CODE_KIND_LABEL) as ProjectCodeKind[]).map((k) => ({ value: k, label: PROJECT_CODE_KIND_LABEL[k] }))}
          placeholder={null}
        />
        <TextField
          label={strings.orgAdmin.codeMinLength}
          value={minLength}
          onChange={setMinLength}
          inputProps={{ min: 1, max: 10, type: "number" }}
        />
        <TextField
          label={strings.orgAdmin.codeMaxLength}
          value={maxLength}
          onChange={setMaxLength}
          inputProps={{ min: 1, max: 10, type: "number" }}
        />
        <LabeledSelect
          label={strings.orgAdmin.codeAssignment}
          value={assignment}
          onChange={(next) => setAssignment(next as ProjectCodeAssignment)}
          options={(Object.keys(PROJECT_CODE_ASSIGNMENT_LABEL) as ProjectCodeAssignment[]).map((a) => ({
            value: a, label: PROJECT_CODE_ASSIGNMENT_LABEL[a],
          }))}
          placeholder={null}
        />
      </FormGrid>
      {valid && (
        <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
          {strings.orgAdmin.codePolicyPreview(describeCodePolicy({ kind, min_length: min, max_length: max, assignment }))}
        </p>
      )}
      <CheckboxField
        label={strings.orgAdmin.enforceCodeEverywhere}
        checked={enforce}
        onChange={setEnforce}
        hint={strings.orgAdmin.enforceCodeEverywhereHint}
      />
      <div className="row">
        <button type="button" className="btn btn-primary" onClick={save} disabled={!valid || saving}>
          {strings.common.save}
        </button>
      </div>
    </div>
  );
}
