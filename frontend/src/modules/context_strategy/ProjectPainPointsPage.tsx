/**
 * Module: modules/context_strategy/ProjectPainPointsPage
 *
 * The Context & Strategy module's project-scoped Pain Point list route
 * (docs/plans/module-01-context-and-strategy-plan.md Phase 7.3), mounted at
 * `/projects/:projectId/modules/context_strategy/pain-points`, reached via
 * this module's third top-level nav-rail entry (Phase 0 Q7). Mirrors
 * `ProjectStrategiesPage.tsx`'s exact `DirectoryTable` + `FilterPanel` +
 * "New X" `Modal` shape — Pain Point is project-scoped only (source overview
 * §6), so unlike that page there is no org-scoped sibling panel.
 *
 * Phase 11 adds per-persona scoring to the list: a Score column (the
 * roll-up under the model and persona roll-up picked in the switcher above
 * the table, "chosen when viewing") and a Blocker badge that stays visible
 * whichever is chosen. The Score column is sortable, so switching model
 * re-ranks the list. Intentional limitations carry an "Intentional" badge
 * and can be hidden from the list via a filter.
 *
 * Also loads this project's effective Pain Point type list
 * (`projectPainPointApi.listTypes`) once, up front — both the type filter
 * dropdown and `PainPointFormModal`'s own type picker need it, and loading
 * it here (rather than inside the modal) avoids a load flash every time the
 * "New Pain Point" modal opens.
 *
 * Filters can be pre-set from the URL (a report figure links here, e.g.
 * `?open=1&blocker=1`): `status`, `priority`, `open=1` (still being worked),
 * `intentional=hide|only`, `blocker=1`, `scored=yes|no`, and `model` /
 * `rollup` (the scoring the report ran with). They only seed the state; each
 * is a visible control in the filter panel, so it can be changed or cleared.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import type { Project } from "../../api/types";
import { api } from "../../api/client";
import { projectScoringApi, type ScoringScheme } from "../../api/scoring";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { ScoringModelSwitcher } from "../../components/ScoringModelSwitcher";
import { Spinner } from "../../components/Spinner";
import { cycleSort, type SortState } from "../../components/sortState";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { oneOf, useInitialSearchParams } from "../../hooks/useInitialSearchParams";
import { projectPainPointApi } from "./api";
import { PainPointFormModal } from "./PainPointFormModal";
import { BlockerBadge, PainPointScoreBadge } from "./PainPointScoreBadges";
import {
  PAIN_POINT_OPEN_STATUSES, PAIN_POINT_PRIORITY_LABEL, PAIN_POINT_ROLLUP_LABEL, PAIN_POINT_STATUS_LABEL, PAIN_POINT_STATUS_TONE,
} from "./types";
import type {
  EffectivePainPointType, PainPoint, PainPointFieldValues, PainPointPriority, PainPointRollup,
  PainPointScoringList, PainPointScoringSummary, PainPointStatus,
} from "./types";

const SCHEME_KEY = "pain_point";

export function ProjectPainPointsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const initial = useInitialSearchParams();
  const [project, setProject] = useState<Project | null>(null);
  const [painPoints, setPainPoints] = useState<PainPoint[] | null>(null);
  const [types, setTypes] = useState<EffectivePainPointType[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<PainPointStatus | "">(() => oneOf(initial.get("status"), Object.keys(PAIN_POINT_STATUS_LABEL) as PainPointStatus[]));
  const [priorityFilter, setPriorityFilter] = useState<PainPointPriority | "">(() => oneOf(initial.get("priority"), Object.keys(PAIN_POINT_PRIORITY_LABEL) as PainPointPriority[]));
  const [includeArchived, setIncludeArchived] = useState(false);
  const [hideIntentional, setHideIntentional] = useState(initial.get("intentional") === "hide");
  const [onlyIntentional, setOnlyIntentional] = useState(initial.get("intentional") === "only");
  const [openOnly, setOpenOnly] = useState(initial.get("open") === "1");
  const [blockersOnly, setBlockersOnly] = useState(initial.get("blocker") === "1");
  const [scoredFilter, setScoredFilter] = useState<"" | "yes" | "no">(() => oneOf(initial.get("scored"), ["yes", "no"] as const));

  const [scheme, setScheme] = useState<ScoringScheme | null>(null);
  const [model, setModel] = useState<string | null>(initial.get("model"));
  const [rollup, setRollup] = useState<PainPointRollup>(
    () => oneOf(initial.get("rollup"), Object.keys(PAIN_POINT_ROLLUP_LABEL) as PainPointRollup[]) || "weighted_average",
  );
  const [scoring, setScoring] = useState<PainPointScoringList | null>(null);
  const [sort, setSort] = useState<SortState | null>(null);

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function reloadPainPoints() {
    if (!projectId) return;
    try {
      setPainPoints(await projectPainPointApi.list(projectId, { include_archived: includeArchived }));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "The Context & Strategy module isn't enabled for this project's organisation, or you don't have access to it."));
    }
  }

  useEffect(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then(setProject);
    void projectPainPointApi.listTypes(projectId).then(setTypes).catch(() => setTypes([]));
  }, [projectId]);

  useEffect(() => {
    void reloadPainPoints();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, includeArchived]);

  useEffect(() => {
    if (!projectId) return;
    void projectScoringApi.get(projectId, SCHEME_KEY).then(setScheme).catch(() => setScheme(null));
  }, [projectId]);

  // Scores are secondary to the list itself: a failure here just leaves the
  // score columns empty rather than hiding the Pain Points.
  useEffect(() => {
    if (!projectId) return;
    projectPainPointApi
      .listScores(projectId, { model_key: model ?? undefined, rollup, include_archived: includeArchived })
      .then((loaded) => { setScoring(loaded); setModel((current) => current ?? loaded.model_key); })
      .catch(() => setScoring(null));
  }, [projectId, model, rollup, includeArchived]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (painPoints === null || project === null) return <Spinner />;

  const summaryById = new Map<string, PainPointScoringSummary>((scoring?.items ?? []).map((i) => [i.pain_point_id, i]));
  const scoreOf = (p: PainPoint) => summaryById.get(p.id)?.score?.normalised ?? null;

  const filtered = painPoints.filter((p) => {
    if (hideIntentional && p.is_intentional) return false;
    if (onlyIntentional && !p.is_intentional) return false;
    if (openOnly && !PAIN_POINT_OPEN_STATUSES.includes(p.status)) return false;
    if (blockersOnly && !summaryById.get(p.id)?.is_blocker) return false;
    if (scoredFilter && (scoreOf(p) !== null) !== (scoredFilter === "yes")) return false;
    if (statusFilter && p.status !== statusFilter) return false;
    if (priorityFilter && p.priority !== priorityFilter) return false;
    if (search && !p.title.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  // Unscored items always sort last, in either direction.
  const rows = sort?.key === "score"
    ? [...filtered].sort((a, b) => {
        const [x, y] = [scoreOf(a), scoreOf(b)];
        if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
        return sort.direction === "asc" ? x - y : y - x;
      })
    : filtered;

  const columns: DirectoryColumn<PainPoint>[] = [
    {
      key: "title", label: "Title",
      render: (p) => (
        <>
          {p.title}
          {p.is_intentional && <span className="badge badge--info" style={{ marginLeft: "0.5rem" }}>Intentional</span>}
        </>
      ),
    },
    { key: "type", label: "Type", render: (p) => p.pain_point_type_name },
    { key: "priority", label: "Priority", render: (p) => PAIN_POINT_PRIORITY_LABEL[p.priority] },
    {
      key: "status", label: "Status",
      render: (p) => <span className={`badge badge--${PAIN_POINT_STATUS_TONE[p.status]}`}>{PAIN_POINT_STATUS_LABEL[p.status]}</span>,
    },
    {
      key: "score", label: "Score", sortable: true,
      render: (p) => {
        const summary = summaryById.get(p.id);
        if (!summary) return "–";
        return (
          <span className="row" style={{ gap: "0.35rem", alignItems: "center" }}>
            <PainPointScoreBadge score={summary.score} />
            <BlockerBadge summary={summary} />
          </span>
        );
      },
    },
  ];

  return (
    <div className="container stack">
      <h1 style={{ margin: 0 }}>Pain Point</h1>
      <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
        New Pain Point
      </button>
      {scheme && model && (
        <ScoringModelSwitcher
          models={scheme.models.map((m) => ({ value: m.key, label: m.label }))}
          model={model}
          onModelChange={setModel}
          rollups={Object.entries(PAIN_POINT_ROLLUP_LABEL).map(([value, label]) => ({ value, label }))}
          rollup={rollup}
          onRollupChange={(next) => setRollup(next as PainPointRollup)}
        />
      )}
      <div className="side-grid">
        <DirectoryTable
          ariaLabel="Pain Points"
          columns={columns}
          rows={rows}
          sort={sort}
          onSort={(key) => setSort((current) => cycleSort(current, key))}
          rowKey={(p) => p.id}
          onRowClick={(p) => navigate(`/projects/${projectId}/modules/context_strategy/pain-points/${p.id}`)}
          emptyState={<p className="text-muted">No Pain Points recorded for this project yet.</p>}
        />
        <FilterPanel
          sectionKey="context_strategy.pain_points.list" total={filtered.length}
          search={search} onSearchChange={setSearch} searchPlaceholder="Search Pain Points…" searchAriaLabel="Search Pain Points"
        >
          <FilterField label="Status">
            <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as PainPointStatus | "")}>
              <option value="">All statuses</option>
              {Object.entries(PAIN_POINT_STATUS_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </FilterField>
          <FilterField label="Priority">
            <select className="input" value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value as PainPointPriority | "")}>
              <option value="">All priorities</option>
              {Object.entries(PAIN_POINT_PRIORITY_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </FilterField>
          <FilterField label="Scoring">
            <select className="input" value={scoredFilter} onChange={(e) => setScoredFilter(e.target.value as "" | "yes" | "no")}>
              <option value="">Any scoring</option>
              <option value="yes">Scored</option>
              <option value="no">Not scored</option>
            </select>
          </FilterField>
          <FilterCheckbox label="Open only" checked={openOnly} onChange={setOpenOnly} />
          <FilterCheckbox label="Blockers only" checked={blockersOnly} onChange={setBlockersOnly} />
          <FilterCheckbox
            label="Hide intentional limitations" checked={hideIntentional}
            onChange={(next) => { setHideIntentional(next); if (next) setOnlyIntentional(false); }}
          />
          <FilterCheckbox
            label="Only intentional limitations" checked={onlyIntentional}
            onChange={(next) => { setOnlyIntentional(next); if (next) setHideIntentional(false); }}
          />
          <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
        </FilterPanel>
      </div>

      {creating && (
        <PainPointFormModal
          types={types}
          error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={async (values: PainPointFieldValues) => {
            setCreateError(null);
            try {
              await projectPainPointApi.create(projectId, values);
              showToast("Pain Point created.");
              setCreating(false);
              await reloadPainPoints();
            } catch (err) {
              setCreateError(toErrorMessage(err, "Could not create Pain Point."));
            }
          }}
        />
      )}
    </div>
  );
}
