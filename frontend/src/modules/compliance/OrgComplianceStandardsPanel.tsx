/**
 * Module: modules/compliance/OrgComplianceStandardsPanel
 *
 * The By standard tab of the Standards page (`StandardsTabs.tsx`, hosted by `ComplianceStatusPage.tsx`): §22's "Organisation
 * Compliance View" (Standard | Projects | Compliant | Non-Compliant | In Progress), grouped client-side from
 * `GET .../project-compliance` (`listOrgProjectComplianceStatus`), whose `ProjectComplianceStatusOut` carries each row's
 * figures (§20). It supports every §22 filter (standard, version, project, state) and drills down to the projects behind an
 * aggregate row and then to that project's Compliance page (§21), not a parallel requirement-level drill-down.
 * - A "Group by" pivot (standard by default, or project) works over the same `statusRows`; `groupBy` and `stateFilter` read
 *   `?groupBy=` and `?state=` so `OrgComplianceWidgets.tsx`'s tiles can link into a pre-filtered, pre-pivoted view.
 * - The expand control is `.disclosure-toggle` (`theme.css`), a borderless row-filling button with fixed-size
 *   `ChevronDown`/`ChevronRight` icons; the expanded list is indented as in `RequirementTree.tsx`. In the group-by-standard
 *   view a row groups its projects by `standard_version_id`, one sub-heading per version; a lone version renders pre-expanded
 *   with no toggle. Group-by-project rows list one row per standard (a project assigns exactly one version).
 * - Export (`ReportExportButton`) passes the Standard, Standard version and Project filters to
 *   `complianceApi.downloadOrgComplianceReport` so the file matches the screen; `groupBy` and `stateFilter` are not passed.
 */
import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { FilterPanel } from "../../components/FilterPanel";
import { FilterSelect } from "../../components/FilterSelect";
import { ListPageLayout } from "../../components/ListPageLayout";
import { ReportExportButton } from "../../components/ReportExportButton";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { downloadBlob } from "../../utils/download";
import * as complianceApi from "./api";
import { OrganisationCell, OrganisationHeader } from "./OrganisationCell";
import {
  COMPLIANCE_OVERALL_STATE_LABEL,
  type ComplianceOverallState,
  type ProjectComplianceStatus,
} from "./types";
import { Badge } from "../../components/Badge";
import { useStrings } from "../../context/TerminologyContext";
import { t } from "../../i18n/strings";
import { useUrlChoice, useUrlText } from "../../hooks/useUrlFilter";
import type { ComplianceStatusFrame } from "./StandardsTabs";
import { COMPLIANCE_FILTER_LABEL } from "./filterLabels";

type GroupBy = "standard" | "project";

/** An assignment row, tagged with the organisation it was read from. */
type StatusRow = complianceApi.InOrganization<ProjectComplianceStatus>;

interface Group {
  key: string;
  /** Full row label, e.g. "ISO-27001 — ISO 27001" for a standard group, or
   * just the project name for a project group. */
  displayLabel: string;
  /** Shorter form used in the expand/collapse control's accessible name, distinct from `displayLabel` so the group-by-standard
   * shape keeps the aria-label text that existing Playwright coverage asserts on verbatim. */
  ariaLabel: string;
  rows: StatusRow[];
}

function groupRows(rows: StatusRow[], groupBy: GroupBy): Group[] {
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

function countByState(rows: StatusRow[], state: ComplianceOverallState): number {
  return rows.filter((r) => r.overall_compliance_state === state).length;
}

interface VersionGroup {
  key: string;
  label: string;
  rows: StatusRow[];
}

/** The second nesting level inside a group-by-standard row's expanded project list: one sub-group per `standard_version_id`,
 * so a standard with projects on several versions reads Standard -> Version -> Project. */
function groupByVersion(rows: StatusRow[]): VersionGroup[] {
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

/**
 * @param frame The Standards page's title-row parts (tab strip, tab panel attributes, Organisation filter) and the
 *   organisations whose assignments are shown.
 */
export function OrgComplianceStandardsPanel({ frame }: { frame: ComplianceStatusFrame }) {
  const { orgs, showOrg } = frame;
  // Export is a per-organisation report; it is offered once the Organisation filter narrows to one.
  const exportOrgId = orgs.length === 1 ? orgs[0].id : null;
  const strings = useStrings();
  const { showToast } = useToast();
  const [statusRows, setStatusRows] = useState<StatusRow[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  // Every filter is in the URL, so the view comes back as it was left after a visit to a project's page, and the
  // summary widget's tiles can open it already narrowed (`?groupBy=project&state=non_compliant`).
  const [groupByChoice, setGroupBy] = useUrlChoice<GroupBy>("groupBy", ["standard", "project"]);
  const groupBy: GroupBy = groupByChoice || "standard";
  const [standardFilter, setStandardFilter] = useUrlText("standard");
  const [versionFilter, setVersionFilter] = useUrlText("version");
  const [projectFilter, setProjectFilter] = useUrlText("project");
  const [stateFilter, setStateFilter] = useUrlChoice<ComplianceOverallState>("state", COMPLIANCE_OVERALL_STATES);
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<Set<string>>(new Set());
  const [expandedVersionKeys, setExpandedVersionKeys] = useState<Set<string>>(new Set());

  useEffect(() => {
    complianceApi
      .collectAcrossOrgs(orgs, (orgId) => complianceApi.listOrgProjectComplianceStatus(orgId))
      .then(setStatusRows)
      .catch((err) => {
        setLoadFailed(true);
        showToast(toErrorMessage(err, "Could not load organisation compliance status."), "error");
      });
  }, [orgs, showToast]);

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

  async function downloadReport(kind: complianceApi.ComplianceReportKind) {
    if (!exportOrgId) return;
    try {
      // Scoped to the panel's current filters: Export means what is on screen. `groupBy` and `stateFilter` have no report
      // equivalent (the server's assignment-row filters mirror this panel's filters only) and are not passed.
      const blob = await complianceApi.downloadOrgComplianceReport(exportOrgId, kind, {
        standardId: standardFilter || undefined,
        standardVersionId: versionFilter || undefined,
        projectId: projectFilter || undefined,
      });
      downloadBlob(blob, `compliance-by-standard-report.${kind}`);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not generate the compliance report."), "error");
    }
  }

  const filter = (
    <FilterPanel sectionKey="orgCompliance.standards" matching={filteredRows.length} total={statusRows?.length ?? 0}>
      {frame.orgFilter}

        <FilterSelect
          label={strings.filters.groupBy}
          value={groupBy}
          onChange={(v) => {
              setGroupBy(v === "standard" ? "" : v);
              // Group keys (project ids versus standard ids) can coincide in value, so the new pivot starts collapsed rather than
              // carrying a stale expansion onto an unrelated group.
              setExpandedGroupKeys(new Set());
            }}
          options={[{ value: "standard", label: "Standard" }, { value: "project", label: "Project" }]}
        />
        <FilterSelect
          label={COMPLIANCE_FILTER_LABEL.standard}
          value={standardFilter}
          onChange={(v) => {
              setStandardFilter(v);
              setVersionFilter("");
            }}
          allLabel="All standards"
          options={standards.map((s) => ({ value: s.id, label: `${s.reference} — ${s.name}` }))}
        />
        <FilterSelect
          label={COMPLIANCE_FILTER_LABEL.standardVersion}
          value={versionFilter}
          onChange={setVersionFilter}
          allLabel="All versions"
          options={versions.map((v) => ({ value: v.id, label: v.label }))}
        />
        <FilterSelect
          label={strings.filters.project}
          value={projectFilter}
          onChange={setProjectFilter}
          allLabel={strings.filters.allProjects}
          options={projects.map((p) => ({ value: p.id, label: p.name }))}
        />
        <FilterSelect
          label="Compliance state"
          value={stateFilter}
          onChange={setStateFilter}
          allLabel="All states"
          options={(Object.keys(COMPLIANCE_OVERALL_STATE_LABEL) as ComplianceOverallState[]).map((state) => ({ value: state, label: COMPLIANCE_OVERALL_STATE_LABEL[state] }))}
        />
    </FilterPanel>
  );

  return (
    <ListPageLayout
      title={t().standardsPage.title}
      actions={exportOrgId && <ReportExportButton onDownload={downloadReport} kinds={complianceApi.COMPLIANCE_REPORT_KINDS} />}
      tabs={frame.tabs}
      contentProps={frame.contentProps}
      filter={filter}
      ready={statusRows !== null}
    >
      {statusRows === null ? (
        loadFailed ? <p className="text-muted">{t().standardsPage.noStatusAccess}</p> : <Spinner />
      ) : (
        <>
        {groups.length === 0 ? (
          <p className="text-muted">No compliance assignments match these filters.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>{groupBy === "project" ? "Project" : "Standard"}</th>
                  <OrganisationHeader show={showOrg} />
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
                        <OrganisationCell name={group.rows[0].organization_name} show={showOrg} />
                        <td>{group.rows.length}</td>
                        <td>{countByState(group.rows, "compliant")}</td>
                        <td>{countByState(group.rows, "non_compliant")}</td>
                        <td>{countByState(group.rows, "in_progress")}</td>
                        <td>{avgPercentage.toFixed(1)}%</td>
                      </tr>
                      {expanded && (
                        <tr>
                          <td colSpan={showOrg ? 7 : 6}>
                            {groupBy === "standard" ? (
                              (() => {
                                const versionGroups = groupByVersion(group.rows);
                                // A lone version behind an explicit "expand this standard" click has nothing to disambiguate,
                                // so it renders pre-expanded with no toggle.
                                const singleVersion = versionGroups.length === 1;
                                return (
                                  <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                                    {versionGroups.map((versionGroup) => {
                                      const versionExpanded = singleVersion || expandedVersionKeys.has(versionGroup.key);
                                      return (
                                        <li
                                          key={versionGroup.key}
                                          style={{ marginLeft: "1.75rem", borderLeft: "2px solid var(--color-border)", paddingLeft: "var(--space-4)", marginBottom: "var(--space-3)" }}
                                        >
                                          {singleVersion ? (
                                            <h4 style={{ margin: "var(--space-1) 0" }}>{versionGroup.label}</h4>
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
                                                paddingLeft: "var(--space-4)",
                                              }}
                                            >
                                              {versionGroup.rows.map((row) => (
                                                <li
                                                  key={row.project_compliance_id}
                                                  className="row"
                                                  style={{ justifyContent: "space-between", borderBottom: "1px solid var(--color-border)", padding: "var(--space-2) 0" }}
                                                >
                                                  <Link to={`/projects/${row.project_id}/modules/compliance`}>{row.project_name}</Link>
                                                  <span>
                                                    <Badge>{COMPLIANCE_OVERALL_STATE_LABEL[row.overall_compliance_state]}</Badge>{" "}
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
                                  paddingLeft: "var(--space-4)",
                                }}
                              >
                                {group.rows.map((row) => (
                                  <li
                                    key={row.project_compliance_id}
                                    className="row"
                                    style={{ justifyContent: "space-between", borderBottom: "1px solid var(--color-border)", padding: "var(--space-2) 0" }}
                                  >
                                    <span>
                                      <Link to={`/projects/${row.project_id}/modules/compliance`}>{`${row.standard_reference} — ${row.standard_name}`}</Link>
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
        </>
      )}
    </ListPageLayout>
  );
}
