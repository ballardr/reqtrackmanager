/**
 * Module: modules/risk_management/ProjectRisksPage
 *
 * The project's risk register, mounted at `/projects/:projectId/modules/
 * risk_management/risks` (`module.ts`, reached from the "Risks" nav-rail
 * entry) —
 *
 * Two views over the same filtered set, switched with `Tabs`:
 * - *Register*: a `DirectoryTable` (code opens the detail page) with inherent
 *   and residual rating, status, owner and next-review columns, plus a
 *   `FilterPanel` (search, status, type, "review overdue", "no effective
 *   treatment yet", archived).
 * - *Matrix*: the configured Likelihood × Consequence grid with the risks
 *   plotted by inherent or residual rating (`RiskMatrix`). Clicking a cell
 *   narrows the register to that cell and returns to it.
 *
 * The register opens on open risks only (the "Open only" filter is ticked and
 * stays visible); a link with a valid `status`, or `open=0`, starts with it
 * off (`hooks/useOpenOnly.ts`). The view, matrix cell and filters are kept in
 * the URL (`hooks/useUrlFilter.ts`), so the register comes back as it was left.
 *
 * Status and type render through their label maps; the rating is derived by the
 * backend. The project, org users, types, scheme and risks are fetched here
 * (no `ProjectContext` provider, as `ProjectDecisionsPage` does).
 */
import { RecordCode } from "../../components/RecordCode";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../../api/client";
import type { OrgUser, Project } from "../../api/types";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterBadge } from "../../components/FilterBadge";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { ListPageLayout } from "../../components/ListPageLayout";
import { LabeledSelect } from "../../components/LabeledSelect";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps } from "../../components/Tabs";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { riskApi } from "./api";
import { countPlottable, type RiskMatrixBasis } from "./riskFields";
import { RiskFormModal } from "./RiskFormModal";
import { RiskMatrix } from "./RiskMatrix";
import { RiskRatingBadge } from "./RiskRatingBadge";
import { CONSEQUENCE_AXIS, LIKELIHOOD_AXIS, levelName, useRiskScheme } from "./useRiskScheme";
import { RISK_OPEN_STATUSES, RISK_STATUS_LABEL, RISK_STATUS_TONE } from "./types";
import type { Risk, RiskFieldValues, RiskStatus } from "./types";
import { Badge } from "../../components/Badge";
import { useInitialSearchParams } from "../../hooks/useInitialSearchParams";
import { useOpenOnly } from "../../hooks/useOpenOnly";
import { useUrlChoice, useUrlFlag, useUrlText } from "../../hooks/useUrlFilter";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
import { rowProjectId } from "../../api/projectScope";
import { ProjectScopeFilter } from "../../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../../components/ProjectScopeLabel";
import { useProjectScope } from "../../hooks/useProjectScope";
import { useTagFilter } from "../../hooks/useTagFilter";
import { TagFilterField } from "../../components/TagFilterField";

type View = "register" | "matrix";

const BASIS_OPTIONS = [
  { value: "inherent", label: "Inherent rating" },
  { value: "residual", label: "Residual rating" },
];

/** A matrix cell the register is narrowed to (the levels of the risk's inherent or residual rating). */
interface CellFilter {
  basis: RiskMatrixBasis;
  likelihoodLevelId: string;
  consequenceLevelId: string;
}

const VIEW_PARAMS: readonly View[] = ["matrix"];
const BASIS_PARAMS: readonly RiskMatrixBasis[] = ["residual"];

/** The matrix cell as one URL value, `basis~likelihoodLevelId~consequenceLevelId`. */
function formatCell(cell: CellFilter): string {
  return [cell.basis, cell.likelihoodLevelId, cell.consequenceLevelId].join("~");
}

/** Reads `formatCell`'s value back; anything malformed is no cell filter. */
function parseCell(value: string): CellFilter | null {
  const [basis, likelihoodLevelId, consequenceLevelId, ...rest] = value.split("~");
  if ((basis !== "inherent" && basis !== "residual") || !likelihoodLevelId || !consequenceLevelId || rest.length > 0) return null;
  return { basis, likelihoodLevelId, consequenceLevelId };
}

function inCell(risk: Risk, cell: CellFilter): boolean {
  const likelihood = cell.basis === "inherent" ? risk.inherent_likelihood_level_id : risk.residual_likelihood_level_id;
  const consequence = cell.basis === "inherent" ? risk.inherent_consequence_level_id : risk.residual_consequence_level_id;
  return likelihood === cell.likelihoodLevelId && consequence === cell.consequenceLevelId;
}

export function ProjectRisksPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { user } = useAuth();
  const { showToast } = useToast();
  const commitQuickLinks = useCommitQuickLinks(projectId ?? "", "risk");
  const commitTags = useCommitTags(projectId ?? "", "risk");
  const initial = useInitialSearchParams();
  const scheme = useRiskScheme(projectId);
  const [project, setProject] = useState<Project | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [riskTypes, setRiskTypes] = useState<{ id: string; name: string }[]>([]);
  const [risks, setRisks] = useState<Risk[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // The view, matrix basis, matrix cell and filters live in the URL so the register comes back as it was
  // left after a visit to a record.
  const [viewParam, setViewParam] = useUrlChoice("view", VIEW_PARAMS);
  const view: View = viewParam || "register";
  const setView = (next: View) => setViewParam(next === "matrix" ? "matrix" : "");
  const [basisParam, setBasisParam] = useUrlChoice("basis", BASIS_PARAMS);
  const basis: RiskMatrixBasis = basisParam || "inherent";
  const setBasis = (next: RiskMatrixBasis) => setBasisParam(next === "residual" ? "residual" : "");
  const [cellParam, setCellParam] = useUrlText("cell");
  const cell = useMemo(() => parseCell(cellParam), [cellParam]);
  const setCell = (next: CellFilter | null) => setCellParam(next ? formatCell(next) : "");
  const [search, setSearch] = useUrlText("q");
  const [statusFilter, setStatusFilter] = useUrlChoice("status", Object.keys(RISK_STATUS_LABEL) as RiskStatus[]);
  const [openOnly, setOpenOnly] = useOpenOnly(initial, Object.keys(RISK_STATUS_LABEL));
  const [typeFilter, setTypeFilter] = useUrlText("type");
  const [overdueOnly, setOverdueOnly] = useUrlFlag("overdue");
  const [untreatedOnly, setUntreatedOnly] = useUrlFlag("untreated");
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then((proj) => {
      setProject(proj);
      api.get<OrgUser[]>(`/api/v1/orgs/${proj.organization_id}/users`).then(setOrgUsers).catch(() => setOrgUsers([]));
    });
    riskApi
      .listTypes(projectId)
      .then((types) => setRiskTypes(types.filter((t) => t.is_enabled).map((t) => ({ id: t.id, name: t.name }))))
      .catch(() => setRiskTypes([]));
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    riskApi
      .list(projectId, { include_archived: includeArchived, tags: tagFilter.tags, tag_mode: tagFilter.mode, project_scope: projectScope.scope })
      .then((list) => {
        if (!active) return;
        setRisks(list);
        setLoadError(null);
      })
      .catch((err) => {
        if (active) setLoadError(toErrorMessage(err, "Risk Management isn't enabled for this project, or you don't have access to it."));
      });
    return () => {
      active = false;
    };
  }, [projectId, includeArchived, refreshKey, tagFilter.tags, tagFilter.mode, projectScope.scope]);

  const matches = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (r: Risk, applyOpenOnly: boolean) => {
      if (applyOpenOnly && !RISK_OPEN_STATUSES.includes(r.status)) return false;
      if (statusFilter && r.status !== statusFilter) return false;
      if (typeFilter && r.risk_type_id !== typeFilter) return false;
      if (overdueOnly && !r.is_review_overdue) return false;
      if (untreatedOnly && r.is_effectively_treated) return false;
      if (cell && !inCell(r, cell)) return false;
      if (needle && !`${r.unique_code} ${r.title} ${r.statement}`.toLowerCase().includes(needle)) return false;
      return true;
    };
  }, [search, statusFilter, typeFilter, overdueOnly, untreatedOnly, cell]);
  const filtered = useMemo(() => (risks ?? []).filter((r) => matches(r, openOnly)), [risks, matches, openOnly]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (risks === null || project === null) return <Spinner />;


  const columns: DirectoryColumn<Risk>[] = [
    { key: "code", label: "Code", render: (r) => <RecordCode code={r.unique_code} ownerProjectCode={r.from_project_code} /> },
    { key: "title", label: "Title", render: (r) => <>{r.title}<ProjectScopeLabel row={r} /></> },
    { key: "type", label: "Type", render: (r) => r.risk_type_name ?? "—" },
    { key: "inherent", label: "Inherent", render: (r) => <RiskRatingBadge rating={r.inherent_rating} /> },
    { key: "residual", label: "Residual", render: (r) => <RiskRatingBadge rating={r.residual_rating} /> },
    {
      key: "status", label: "Status",
      render: (r) => (
        <FilterBadge
          tone={RISK_STATUS_TONE[r.status]} active={statusFilter === r.status}
          onClick={() => setStatusFilter(statusFilter === r.status ? "" : r.status)}
        >
          {RISK_STATUS_LABEL[r.status]}
        </FilterBadge>
      ),
    },
    { key: "owner", label: "Owner", render: (r) => <PrincipalBadge principal={r.owner} placeholder="—" /> },
    {
      key: "review", label: "Next review",
      render: (r) => r.review_date
        ? <span>{r.review_date}{r.is_review_overdue && <> <Badge tone="danger">Overdue</Badge></>}</span>
        : "—",
    },
  ];

  // An empty register the "Open only" default caused says so, so it is not read as "nothing recorded".
  const emptyBecauseOfOpenOnly = openOnly && filtered.length === 0 && risks.some((r) => matches(r, false));
  const unplotted = filtered.length - countPlottable(filtered, basis);

  return (
    <div className="container stack">
      <ListPageLayout
        title="Risks"
        actions={
          <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
            New risk
          </button>
        }
        filter={
          <FilterPanel
            sectionKey="risks.list" total={filtered.length}
            search={search} onSearchChange={setSearch} searchPlaceholder="Search risks…" searchAriaLabel="Search risks"
          >
            <FilterField label="Status">
              <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as RiskStatus | "")}>
                <option value="">All statuses</option>
                {Object.entries(RISK_STATUS_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </FilterField>
            <FilterField label="Risk type">
              <select className="input" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                <option value="">All types</option>
                {riskTypes.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </FilterField>
            <FilterCheckbox label="Open only" checked={openOnly} onChange={setOpenOnly} />
            <FilterCheckbox label="Review overdue" checked={overdueOnly} onChange={setOverdueOnly} />
            <FilterCheckbox label="No effective treatment" checked={untreatedOnly} onChange={setUntreatedOnly} />
            <ProjectScopeFilter scope={projectScope} />
            {projectId && <TagFilterField projectId={projectId} filter={tagFilter} />}
            <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
          </FilterPanel>
        }
      >
        <Tabs
          idPrefix="risks-view"
          tabs={[{ key: "register", label: "Register" }, { key: "matrix", label: "Matrix" }]}
          active={view}
          onChange={setView}
        />
          <div className="stack" {...tabPanelProps("risks-view", view)}>
            {cell && (
              <div className="row" style={{ gap: "var(--space-3)", alignItems: "center" }}>
                <Badge>
                  {cell.basis === "inherent" ? "Inherent" : "Residual"}:{" "}
                  {levelName(scheme, LIKELIHOOD_AXIS, cell.likelihoodLevelId)} likelihood,{" "}
                  {levelName(scheme, CONSEQUENCE_AXIS, cell.consequenceLevelId)} consequence
                </Badge>
                <button className="btn" onClick={() => setCell(null)}>Clear matrix filter</button>
              </div>
            )}
            {view === "register" ? (
              <DirectoryTable
                ariaLabel="Risks"
                columns={columns}
                rows={filtered}
                rowKey={(r) => r.id}
                rowHref={(r) => `/projects/${rowProjectId(r, projectId)}/modules/risk_management/risks/${r.id}`}
                emptyState={
                  <p className="text-muted">
                    {emptyBecauseOfOpenOnly
                      ? "No open Risks. Untick Open only to include transferred, avoided, realised, rejected and closed ones."
                      : risks.length === 0 ? "No Risks recorded for this project yet." : "No Risks match these filters."}
                  </p>
                }
              />
            ) : (
              <div className="stack">
                <LabeledSelect helpNotNeeded
                  label="Plot by" value={basis} onChange={(next) => setBasis(next as RiskMatrixBasis)}
                  options={BASIS_OPTIONS} placeholder={null}
                />
                <RiskMatrix
                  scheme={scheme} risks={filtered} basis={basis}
                  onCellClick={(likelihoodLevelId, consequenceLevelId) => {
                    setCell({ basis, likelihoodLevelId, consequenceLevelId });
                    setView("register");
                  }}
                />
                {unplotted > 0 && (
                  <p className="text-muted" style={{ margin: 0 }}>
                    {unplotted} risk{unplotted === 1 ? " has" : "s have"} no {basis} likelihood and consequence, so {unplotted === 1 ? "isn't" : "aren't"} plotted.
                  </p>
                )}
              </div>
            )}
          </div>
      </ListPageLayout>

      {creating && (
        <RiskFormModal
          scheme={scheme}
          riskTypes={riskTypes}
          orgUsers={orgUsers}
          organizationId={project.organization_id}
          projectId={projectId}
          currentUserId={user?.id}
          error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={async (values: RiskFieldValues, _changeNote, quickLinks, tags) => {
            setCreateError(null);
            try {
              const created = await riskApi.create(projectId, values);
              showToast("Risk created.");
              setCreating(false);
              await commitQuickLinks(created.id, quickLinks);
              await commitTags(created.id, tags);
              setRefreshKey((k) => k + 1);
            } catch (err) {
              setCreateError(toErrorMessage(err, "Could not create risk."));
            }
          }}
        />
      )}
    </div>
  );
}
