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
      <div className="row" style={{ gap: "1rem", alignItems: "flex-end" }}>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.orgAdmin.codeKind}
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value as ProjectCodeKind)}>
            {(Object.keys(PROJECT_CODE_KIND_LABEL) as ProjectCodeKind[]).map((k) => (
              <option key={k} value={k}>{PROJECT_CODE_KIND_LABEL[k]}</option>
            ))}
          </select>
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.orgAdmin.codeMinLength}
          <input className="input" type="number" min={1} max={10} style={{ width: "5rem" }} value={minLength} onChange={(e) => setMinLength(e.target.value)} />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.orgAdmin.codeMaxLength}
          <input className="input" type="number" min={1} max={10} style={{ width: "5rem" }} value={maxLength} onChange={(e) => setMaxLength(e.target.value)} />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          {strings.orgAdmin.codeAssignment}
          <select className="input" value={assignment} onChange={(e) => setAssignment(e.target.value as ProjectCodeAssignment)}>
            {(Object.keys(PROJECT_CODE_ASSIGNMENT_LABEL) as ProjectCodeAssignment[]).map((a) => (
              <option key={a} value={a}>{PROJECT_CODE_ASSIGNMENT_LABEL[a]}</option>
            ))}
          </select>
        </label>
      </div>
      {valid && (
        <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
          {strings.orgAdmin.codePolicyPreview(describeCodePolicy({ kind, min_length: min, max_length: max, assignment }))}
        </p>
      )}
      <label className="row">
        <input type="checkbox" checked={enforce} onChange={(e) => setEnforce(e.target.checked)} />
        {strings.orgAdmin.enforceCodeEverywhere}
      </label>
      <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>{strings.orgAdmin.enforceCodeEverywhereHint}</p>
      <div className="row">
        <button type="button" className="btn btn-primary" onClick={save} disabled={!valid || saving}>
          {strings.common.save}
        </button>
      </div>
    </div>
  );
}
