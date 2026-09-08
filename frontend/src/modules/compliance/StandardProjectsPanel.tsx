/**
 * Module: modules/compliance/StandardProjectsPanel
 *
 * The standard workspace's "Projects" section (docs/compliance-module-
 * plan.md Phase 23) — the destination for the Overview's "Projects"/
 * "Compliant" `MetricTile`s: a simple, single-standard list of every
 * project this standard is assigned to, each with its own §20 overall
 * status, drilling through to that project's own Compliance page
 * (`/projects/:id/modules/compliance`) rather than rebuilding a
 * requirement-level view here — the exact reuse-the-existing-page
 * reasoning `OrgComplianceStandardsPanel.tsx`'s own docstring already
 * gives for its per-standard row expansion.
 *
 * Deliberately not a second `FilterPanel`/`DirectoryTable` directory: this
 * is a single standard's own project list, typically small, reached from
 * one Overview stat tile — the "Compliant" tile's `?state=compliant` query
 * param (read via `useSearchParams`, not local state, so the filtered view
 * is itself linkable/shareable) is the only filter this scope needs.
 */
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import { COMPLIANCE_OVERALL_STATE_LABEL, type ComplianceOverallState, type ComplianceStandard, type ProjectComplianceStatus } from "./types";

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
      <label className="stack" style={{ gap: "0.25rem", maxWidth: 220 }}>
        <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>Compliance state</span>
        <select
          className="input"
          value={stateFilter}
          onChange={(e) => {
            const value = e.target.value;
            setSearchParams(value ? { state: value } : {});
          }}
        >
          <option value="">All states</option>
          {(Object.keys(COMPLIANCE_OVERALL_STATE_LABEL) as ComplianceOverallState[]).map((state) => (
            <option key={state} value={state}>{COMPLIANCE_OVERALL_STATE_LABEL[state]}</option>
          ))}
        </select>
      </label>

      {filtered.length === 0 ? (
        <p className="text-muted">No projects match this filter.</p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {filtered.map((row) => (
            <li
              key={row.project_compliance_id}
              className="row"
              style={{ justifyContent: "space-between", padding: "0.5rem 0", borderBottom: "1px solid var(--color-border)" }}
            >
              <span>
                <Link to={`/projects/${row.project_id}/modules/compliance`}>{row.project_name}</Link>
                <span className="text-muted"> — {row.version_label}</span>
              </span>
              <span>
                <span className="badge">{COMPLIANCE_OVERALL_STATE_LABEL[row.overall_compliance_state]}</span>{" "}
                {row.compliance_percentage.toFixed(1)}%
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
