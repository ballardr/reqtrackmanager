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
 *
 * Phase 39 fixes three defects in the expanded row: **39a** the expand/
 * collapse control no longer renders as a separately bordered `.btn` chip
 * — it's `.disclosure-toggle` (`theme.css`), a borderless row-filling
 * button, the third instance of this fix after `StandardNavSection.tsx`
 * (Phase 29d) and `EntitySwitcher.tsx` (Phase 35b); its `▾`/`▸` text
 * glyphs are also replaced with fixed-size `ChevronDown`/`ChevronRight`
 * icons, matching Phase 29d's own icon choice. **39c** the expanded child
 * list is indented under its parent row using `RequirementTree.tsx`'s own
 * nested-list convention (`marginLeft`/`borderLeft`/`paddingLeft`) so it
 * reads as a tree rather than a flush-left list. **39d** the default
 * (group-by-standard) view's expanded row now groups its projects by
 * `standard_version_id` first, rendering one sub-heading per version with
 * that version's projects nested a level deeper underneath — so a user no
 * longer has to read every row's own version suffix to see which versions
 * of a standard are actually in use. This is additive to the "Group by"
 * pivot, not a third option — group-by-project's expanded row is
 * unaffected (it lists one row per standard already, which has no further
 * version dimension to add: a project's own assignment of a standard has
 * exactly one, unambiguous version). Each version sub-group is itself
 * collapsible when a standard has more than one — but when it has only
 * one, that sub-group renders pre-expanded with no toggle at all, since a
 * lone version behind an already-explicit "expand this standard" click has
 * nothing left to disambiguate (Decided by: User, live follow-up during
 * this phase's implementation).
 *
 * Phase 43 adds an "Export" trigger (`ReportExportButton`, the same shape
 * `OrgComplianceDashboard.tsx`'s own report download uses) above the table,
 * scoped to this panel's current Standard/Standard version/Project filters
 * — `complianceApi.downloadOrgComplianceReport` passes them through as
 * query params so the downloaded PDF/CSV matches what's on screen, not an
 * unfiltered organisation-wide dump. `groupBy`/`stateFilter` have no
 * report-side equivalent and aren't passed through — see this panel's own
 * `downloadReport` for why.
 */
import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { FilterField, FilterPanel } from "../../components/FilterPanel";
import { ReportExportButton } from "../../components/ReportExportButton";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { downloadBlob } from "../../utils/download";
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

interface VersionGroup {
  key: string;
  label: string;
  rows: ProjectComplianceStatus[];
}

/** 39d: the second nesting level inside a group-by-standard row's expanded
 * project list — one sub-group per `standard_version_id`, so a standard
 * with projects on more than one version reads as Standard -> Version ->
 * Project rather than a flat list of projects each carrying their own
 * version suffix. */
function groupByVersion(rows: ProjectComplianceStatus[]): VersionGroup[] {
  const byVersion = new Map<string, VersionGroup>();
  for (const row of rows) {
    let group = byVersion.get(row.standard_version_id);
    if (!group) {
      group = { key: row.standard_version_id, label: row.version_label, rows: [] };
      byVersion.set(row.standard_version_id, group);
    }
    group.rows.push(row);
  }
  return [...byVersion.values()].sort((a, b) => a.label.localeCompare(b.label));
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
  const [expandedVersionKeys, setExpandedVersionKeys] = useState<Set<string>>(new Set());

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

  function toggleVersionExpanded(versionKey: string) {
    setExpandedVersionKeys((prev) => {
      const next = new Set(prev);
      if (next.has(versionKey)) next.delete(versionKey);
      else next.add(versionKey);
      return next;
    });
  }

  async function downloadReport(kind: "pdf" | "csv") {
    try {
      // Scoped to this panel's own current filters (Phase 43) — "Export"
      // means "export what I'm looking at," not the whole organisation.
      // `groupBy`/`stateFilter` have no report-side equivalent (the
      // backend's assignment-row filter set mirrors this panel's Phase 40
      // filters only) and are deliberately not passed through.
      const blob = await complianceApi.downloadOrgComplianceReport(orgId, kind, {
        standardId: standardFilter || undefined,
        standardVersionId: versionFilter || undefined,
        projectId: projectFilter || undefined,
      });
      downloadBlob(blob, `compliance-by-standard-report.${kind}`);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not generate the compliance report."), "error");
    }
  }

  if (statusRows === null) return <Spinner />;

  return (
    <div className="side-grid">
      <div className="stack">
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <ReportExportButton onDownload={downloadReport} />
        </div>
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
                            className="disclosure-toggle"
                            aria-expanded={expanded}
                            aria-label={`${expanded ? "Collapse" : "Expand"} ${counterpartNoun} for ${group.ariaLabel}`}
                            onClick={() => toggleExpanded(group.key)}
                          >
                            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                            {group.displayLabel}
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
                            {groupBy === "standard" ? (
                              (() => {
                                const versionGroups = groupByVersion(group.rows);
                                // A lone version behind an already-explicit "expand this
                                // standard" click has nothing left to disambiguate — render it
                                // pre-expanded with no toggle of its own, rather than making the
                                // user click twice to see the one project list that exists.
                                const singleVersion = versionGroups.length === 1;
                                return (
                                  <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                                    {versionGroups.map((versionGroup) => {
                                      const versionExpanded = singleVersion || expandedVersionKeys.has(versionGroup.key);
                                      return (
                                        <li
                                          key={versionGroup.key}
                                          style={{ marginLeft: "1.75rem", borderLeft: "2px solid var(--color-border)", paddingLeft: "0.75rem", marginBottom: "0.5rem" }}
                                        >
                                          {singleVersion ? (
                                            <h4 style={{ margin: "0.25rem 0" }}>{versionGroup.label}</h4>
                                          ) : (
                                            <button
                                              type="button"
                                              className="disclosure-toggle"
                                              aria-expanded={versionExpanded}
                                              aria-label={`${versionExpanded ? "Collapse" : "Expand"} projects for ${versionGroup.label}`}
                                              onClick={() => toggleVersionExpanded(versionGroup.key)}
                                            >
                                              {versionExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                              <strong>{versionGroup.label}</strong>
                                            </button>
                                          )}
                                          {versionExpanded && (
                                            <ul
                                              style={{
                                                listStyle: "none",
                                                margin: 0,
                                                padding: 0,
                                                marginLeft: "1.75rem",
                                                borderLeft: "2px solid var(--color-border)",
                                                paddingLeft: "0.75rem",
                                              }}
                                            >
                                              {versionGroup.rows.map((row) => (
                                                <li
                                                  key={row.project_compliance_id}
                                                  className="row"
                                                  style={{ justifyContent: "space-between", borderBottom: "1px solid var(--color-border)", padding: "0.35rem 0" }}
                                                >
                                                  <Link to={`/projects/${row.project_id}/modules/compliance`}>{row.project_name}</Link>
                                                  <span>
                                                    <span className="badge">{COMPLIANCE_OVERALL_STATE_LABEL[row.overall_compliance_state]}</span>{" "}
                                                    {row.compliance_percentage.toFixed(1)}%
                                                  </span>
                                                </li>
                                              ))}
                                            </ul>
                                          )}
                                        </li>
                                      );
                                    })}
                                  </ul>
                                );
                              })()
                            ) : (
                              <ul
                                style={{
                                  listStyle: "none",
                                  margin: 0,
                                  padding: 0,
                                  marginLeft: "1.75rem",
                                  borderLeft: "2px solid var(--color-border)",
                                  paddingLeft: "0.75rem",
                                }}
                              >
                                {group.rows.map((row) => (
                                  <li
                                    key={row.project_compliance_id}
                                    className="row"
                                    style={{ justifyContent: "space-between", borderBottom: "1px solid var(--color-border)", padding: "0.35rem 0" }}
                                  >
                                    <span>
                                      <Link to={`/projects/${row.project_id}/modules/compliance`}>{`${row.standard_reference} — ${row.standard_name}`}</Link>
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
