/**
 * Module: modules/compliance/StandardProjectsPanel
 *
 * The standard workspace's "Projects" section, the destination of the Overview's "Projects" and "Compliant" `MetricTile`s: a
 * simple list of every project the standard is assigned to with its §20 overall status, each drilling to that project's
 * Compliance page (`/projects/:id/modules/compliance`) rather than rebuilding a requirement-level view, as
 * `OrgComplianceStandardsPanel.tsx` does for its row expansion. It is not a second `FilterPanel`/`DirectoryTable` directory:
 * the list is typically small, and the "Compliant" tile's `?state=compliant` query parameter (read with `useSearchParams` so the
 * filtered view is linkable) is the only filter needed.
 */
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import { COMPLIANCE_OVERALL_STATE_LABEL, type ComplianceOverallState, type ComplianceStandard, type ProjectComplianceStatus } from "./types";
import { Badge } from "../../components/Badge";
import { LabeledSelect } from "../../components/LabeledSelect";

export function StandardProjectsPanel({ orgId, standard }: { orgId: string; standard: ComplianceStandard }) {
  const { showToast } = useToast();
  const [rows, setRows] = useState<ProjectComplianceStatus[] | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const stateFilter = (searchParams.get("state") as ComplianceOverallState | null) ?? "";

  useEffect(() => {
    complianceApi
      .getStandardProjectSummary(orgId, standard.id)
      .then(setRows)
      .catch((err) => showToast(toErrorMessage(err, "Could not load this standard's projects."), "error"));
  }, [orgId, standard.id, showToast]);

  if (rows === null) return <Spinner />;

  const filtered = stateFilter ? rows.filter((r) => r.overall_compliance_state === stateFilter) : rows;

  return (
    <div className="stack">
      <LabeledSelect helpNotNeeded
        label="Compliance state"
        value={stateFilter}
        onChange={(next) => setSearchParams(next ? { state: next } : {})}
        options={(Object.keys(COMPLIANCE_OVERALL_STATE_LABEL) as ComplianceOverallState[]).map((state) => ({
          value: state, label: COMPLIANCE_OVERALL_STATE_LABEL[state],
        }))}
        placeholder="All states"
      />

      {filtered.length === 0 ? (
        <p className="text-muted">No projects match this filter.</p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {filtered.map((row) => (
            <li
              key={row.project_compliance_id}
              className="row"
              style={{ justifyContent: "space-between", padding: "var(--space-3) 0", borderBottom: "1px solid var(--color-border)" }}
            >
              <span>
                <Link to={`/projects/${row.project_id}/modules/compliance`}>{row.project_name}</Link>
                <span className="text-muted"> — {row.version_label}</span>
              </span>
              <span>
                <Badge>{COMPLIANCE_OVERALL_STATE_LABEL[row.overall_compliance_state]}</Badge>{" "}
                {row.compliance_percentage.toFixed(1)}%
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
