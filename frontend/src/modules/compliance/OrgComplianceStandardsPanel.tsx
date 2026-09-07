/**
 * Module: modules/compliance/OrgComplianceStandardsPanel
 *
 * §22's "Organisation Compliance View" table — the org-wide "Standard |
 * Projects | Compliant | Non-Compliant | In Progress" summary, grouped
 * client-side (mirroring `api.ts::buildRequirementTree`'s Phase 12
 * precedent for client-side aggregation over a flat backend listing) from
 * `GET .../project-compliance` (`listOrgProjectComplianceStatus`) —
 * `ProjectComplianceStatusOut` already carries everything one row needs
 * (§20's per-assignment overall state/percentage/counts), so no new
 * backend shape was needed for the grouping itself, only the filters.
 *
 * Supports every filter §22 names explicitly (standard, standard version,
 * project, compliance state) and drills down past the aggregate row to
 * the individual projects behind it, then further to that project's own
 * Compliance page — which already drills down to individual requirements
 * (§21's own drill-down chain, Phase 13) — rather than rebuilding a
 * parallel requirement-level drill-down at org scope. See
 * docs/compliance-module-plan.md's Phase 14 notes for why this reuse-the-
 * existing-page approach was chosen over a second requirement browser.
 */
import { Fragment, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import type { ComplianceOverallState } from "../../api/types";
import { COMPLIANCE_OVERALL_STATE_LABEL } from "../../api/types";
import { FilterField, FilterPanel } from "../../components/FilterPanel";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type { ProjectComplianceStatus } from "./types";

interface StandardGroup {
  standardId: string;
  standardReference: string;
  standardName: string;
  rows: ProjectComplianceStatus[];
}

function groupByStandard(rows: ProjectComplianceStatus[]): StandardGroup[] {
  const byStandard = new Map<string, StandardGroup>();
  for (const row of rows) {
    let group = byStandard.get(row.standard_id);
    if (!group) {
      group = { standardId: row.standard_id, standardReference: row.standard_reference, standardName: row.standard_name, rows: [] };
      byStandard.set(row.standard_id, group);
    }
    group.rows.push(row);
  }
  return [...byStandard.values()].sort((a, b) => a.standardReference.localeCompare(b.standardReference));
}

function countByState(rows: ProjectComplianceStatus[], state: ComplianceOverallState): number {
  return rows.filter((r) => r.overall_compliance_state === state).length;
}

export function OrgComplianceStandardsPanel({ orgId }: { orgId: string }) {
  const { showToast } = useToast();
  const [statusRows, setStatusRows] = useState<ProjectComplianceStatus[] | null>(null);
  const [standardFilter, setStandardFilter] = useState("");
  const [versionFilter, setVersionFilter] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [stateFilter, setStateFilter] = useState<ComplianceOverallState | "">("");
  const [expandedStandardIds, setExpandedStandardIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    complianceApi
      .listOrgProjectComplianceStatus(orgId)
      .then(setStatusRows)
      .catch((err) => showToast(toErrorMessage(err, "Could not load organisation compliance status."), "error"));
  }, [orgId, showToast]);

  const standards = useMemo(() => {
    if (!statusRows) return [];
    const map = new Map<string, { id: string; reference: string; name: string }>();
    for (const row of statusRows) map.set(row.standard_id, { id: row.standard_id, reference: row.standard_reference, name: row.standard_name });
    return [...map.values()].sort((a, b) => a.reference.localeCompare(b.reference));
  }, [statusRows]);

  const versions = useMemo(() => {
    if (!statusRows) return [];
    const map = new Map<string, { id: string; label: string }>();
    for (const row of statusRows) {
      if (standardFilter && row.standard_id !== standardFilter) continue;
      map.set(row.standard_version_id, { id: row.standard_version_id, label: `${row.standard_reference} ${row.version_label}` });
    }
    return [...map.values()].sort((a, b) => a.label.localeCompare(b.label));
  }, [statusRows, standardFilter]);

  const projects = useMemo(() => {
    if (!statusRows) return [];
    const map = new Map<string, { id: string; name: string }>();
    for (const row of statusRows) map.set(row.project_id, { id: row.project_id, name: row.project_name });
    return [...map.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [statusRows]);

  const filteredRows = useMemo(() => {
    if (!statusRows) return [];
    return statusRows.filter((row) => {
      if (standardFilter && row.standard_id !== standardFilter) return false;
      if (versionFilter && row.standard_version_id !== versionFilter) return false;
      if (projectFilter && row.project_id !== projectFilter) return false;
      if (stateFilter && row.overall_compliance_state !== stateFilter) return false;
      return true;
    });
  }, [statusRows, standardFilter, versionFilter, projectFilter, stateFilter]);

  const groups = useMemo(() => groupByStandard(filteredRows), [filteredRows]);

  function toggleExpanded(standardId: string) {
    setExpandedStandardIds((prev) => {
      const next = new Set(prev);
      if (next.has(standardId)) next.delete(standardId);
      else next.add(standardId);
      return next;
    });
  }

  if (statusRows === null) return <Spinner />;

  return (
    <div className="side-grid">
      <FilterPanel sectionKey="orgCompliance.standards" matching={filteredRows.length} total={statusRows.length}>
        <FilterField label="Standard">
          <select
            className="input"
            value={standardFilter}
            onChange={(e) => {
              setStandardFilter(e.target.value);
              setVersionFilter("");
            }}
          >
            <option value="">All standards</option>
            {standards.map((s) => (
              <option key={s.id} value={s.id}>{s.reference} — {s.name}</option>
            ))}
          </select>
        </FilterField>
        <FilterField label="Standard version">
          <select className="input" value={versionFilter} onChange={(e) => setVersionFilter(e.target.value)}>
            <option value="">All versions</option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>{v.label}</option>
            ))}
          </select>
        </FilterField>
        <FilterField label="Project">
          <select className="input" value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)}>
            <option value="">All projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </FilterField>
        <FilterField label="Compliance state">
          <select
            className="input"
            value={stateFilter}
            onChange={(e) => setStateFilter(e.target.value as ComplianceOverallState | "")}
          >
            <option value="">All states</option>
            {(Object.keys(COMPLIANCE_OVERALL_STATE_LABEL) as ComplianceOverallState[]).map((state) => (
              <option key={state} value={state}>{COMPLIANCE_OVERALL_STATE_LABEL[state]}</option>
            ))}
          </select>
        </FilterField>
      </FilterPanel>

      <div className="stack">
        {groups.length === 0 ? (
          <p className="text-muted">No compliance assignments match these filters.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Standard</th>
                  <th>Projects</th>
                  <th>Compliant</th>
                  <th>Non-Compliant</th>
                  <th>In Progress</th>
                  <th>Avg. compliance</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((group) => {
                  const expanded = expandedStandardIds.has(group.standardId);
                  const avgPercentage =
                    group.rows.reduce((sum, r) => sum + r.compliance_percentage, 0) / group.rows.length;
                  return (
                    <Fragment key={group.standardId}>
                      <tr>
                        <td>
                          <button
                            type="button"
                            className="btn"
                            aria-expanded={expanded}
                            aria-label={`${expanded ? "Collapse" : "Expand"} projects for ${group.standardReference}`}
                            onClick={() => toggleExpanded(group.standardId)}
                          >
                            {expanded ? "▾" : "▸"} {group.standardReference} — {group.standardName}
                          </button>
                        </td>
                        <td>{group.rows.length}</td>
                        <td>{countByState(group.rows, "compliant")}</td>
                        <td>{countByState(group.rows, "non_compliant")}</td>
                        <td>{countByState(group.rows, "in_progress")}</td>
                        <td>{avgPercentage.toFixed(1)}%</td>
                      </tr>
                      {expanded && (
                        <tr>
                          <td colSpan={6}>
                            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                              {group.rows.map((row) => (
                                <li
                                  key={row.project_compliance_id}
                                  className="row"
                                  style={{ justifyContent: "space-between", borderBottom: "1px solid var(--color-border)", padding: "0.35rem 0" }}
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
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
