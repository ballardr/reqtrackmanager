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
 *
 * Phase 36 added a "Group by" pivot (standard, the original/default shape,
 * or project) over the exact same `statusRows` — the "way to view all
 * projects for a compliance manager" that phase asked for, following the
 * user's own suggested direction of extending this tab rather than adding
 * a fourth widget shape elsewhere. `groupBy`/`stateFilter` also read an
 * initial value off the URL (`?groupBy=`/`?state=`) so `OrgComplianceDashboard.tsx`'s
 * top-grid tiles can link straight into a pre-filtered, pre-pivoted view
 * rather than landing on the unfiltered default and asking the user to
 * re-apply the same filter the tile already counted.
 */
import { Fragment, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { FilterField, FilterPanel } from "../../components/FilterPanel";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import {
  COMPLIANCE_OVERALL_STATE_LABEL,
  type ComplianceOverallState,
  type ProjectComplianceStatus,
} from "./types";

type GroupBy = "standard" | "project";

interface Group {
  key: string;
  /** Full row label, e.g. "ISO-27001 — ISO 27001" for a standard group, or
   * just the project name for a project group. */
  displayLabel: string;
  /** Shorter form used in the expand/collapse control's accessible name —
   * kept distinct from `displayLabel` so the default (group-by-standard)
   * shape's aria-label text is unchanged from before this pivot existed
   * (existing Playwright coverage asserts on it verbatim). */
  ariaLabel: string;
  rows: ProjectComplianceStatus[];
}

function groupRows(rows: ProjectComplianceStatus[], groupBy: GroupBy): Group[] {
  const byKey = new Map<string, Group>();
  for (const row of rows) {
    const key = groupBy === "project" ? row.project_id : row.standard_id;
    let group = byKey.get(key);
    if (!group) {
      group =
        groupBy === "project"
          ? { key, displayLabel: row.project_name, ariaLabel: row.project_name, rows: [] }
          : { key, displayLabel: `${row.standard_reference} — ${row.standard_name}`, ariaLabel: row.standard_reference, rows: [] };
      byKey.set(key, group);
    }
    group.rows.push(row);
  }
  return [...byKey.values()].sort((a, b) => a.displayLabel.localeCompare(b.displayLabel));
}

function countByState(rows: ProjectComplianceStatus[], state: ComplianceOverallState): number {
  return rows.filter((r) => r.overall_compliance_state === state).length;
}

const COMPLIANCE_OVERALL_STATES = Object.keys(COMPLIANCE_OVERALL_STATE_LABEL) as ComplianceOverallState[];

export function OrgComplianceStandardsPanel({ orgId }: { orgId: string }) {
  const { showToast } = useToast();
  const [searchParams] = useSearchParams();
  const [statusRows, setStatusRows] = useState<ProjectComplianceStatus[] | null>(null);
  const [groupBy, setGroupBy] = useState<GroupBy>(() => (searchParams.get("groupBy") === "project" ? "project" : "standard"));
  const [standardFilter, setStandardFilter] = useState("");
  const [versionFilter, setVersionFilter] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [stateFilter, setStateFilter] = useState<ComplianceOverallState | "">(() => {
    const initial = searchParams.get("state");
    return initial && COMPLIANCE_OVERALL_STATES.includes(initial as ComplianceOverallState) ? (initial as ComplianceOverallState) : "";
  });
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<Set<string>>(new Set());

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

  const groups = useMemo(() => groupRows(filteredRows, groupBy), [filteredRows, groupBy]);
  const counterpartNoun = groupBy === "project" ? "standards" : "projects";

  function toggleExpanded(groupKey: string) {
    setExpandedGroupKeys((prev) => {
      const next = new Set(prev);
      if (next.has(groupKey)) next.delete(groupKey);
      else next.add(groupKey);
      return next;
    });
  }

  if (statusRows === null) return <Spinner />;

  return (
    <div className="side-grid">
      <div className="stack">
        {groups.length === 0 ? (
          <p className="text-muted">No compliance assignments match these filters.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>{groupBy === "project" ? "Project" : "Standard"}</th>
                  <th>{groupBy === "project" ? "Standards" : "Projects"}</th>
                  <th>Compliant</th>
                  <th>Non-Compliant</th>
                  <th>In Progress</th>
                  <th>Avg. compliance</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((group) => {
                  const expanded = expandedGroupKeys.has(group.key);
                  const avgPercentage =
                    group.rows.reduce((sum, r) => sum + r.compliance_percentage, 0) / group.rows.length;
                  return (
                    <Fragment key={group.key}>
                      <tr>
                        <td>
                          <button
                            type="button"
                            className="btn"
                            aria-expanded={expanded}
                            aria-label={`${expanded ? "Collapse" : "Expand"} ${counterpartNoun} for ${group.ariaLabel}`}
                            onClick={() => toggleExpanded(group.key)}
                          >
                            {expanded ? "▾" : "▸"} {group.displayLabel}
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
                                    <Link to={`/projects/${row.project_id}/modules/compliance`}>
                                      {groupBy === "project" ? `${row.standard_reference} — ${row.standard_name}` : row.project_name}
                                    </Link>
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

      <FilterPanel sectionKey="orgCompliance.standards" matching={filteredRows.length} total={statusRows.length}>
        <FilterField label="Group by">
          <select
            className="input"
            value={groupBy}
            onChange={(e) => {
              setGroupBy(e.target.value as GroupBy);
              // Different group keys (project ids vs standard ids) can
              // coincidentally overlap in value; simplest to just start
              // collapsed again rather than risk a stale expand carrying
              // over onto an unrelated group under the new pivot.
              setExpandedGroupKeys(new Set());
            }}
          >
            <option value="standard">Standard</option>
            <option value="project">Project</option>
          </select>
        </FilterField>
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
    </div>
  );
}
