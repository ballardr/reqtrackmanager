/**
 * Module: modules/context_strategy/ProjectPainPointsPage
 *
 * The project-scoped Pain Point list route, mounted at `/projects/:projectId/modules/context_strategy/pain-points`
 * (the module's third top-level nav-rail entry). It has `ProjectStrategiesPage.tsx`'s `DirectoryTable`, `FilterPanel`
 * and "New X" `Modal` shape; Pain Point is project-scoped only, so there is no organisation-scoped sibling panel.
 *
 * Per-persona scoring shows in the list: a sortable Score column (the roll-up under the model and persona roll-up
 * chosen in the column header gear, so switching model re-ranks the list) and a Blocker badge after the title that
 * stays visible whichever is chosen. Intentional limitations carry an "Intentional" badge and can be hidden with a
 * filter.
 *
 * The list opens on open Pain Points only (the "Open only" filter is ticked and visible). A link that names a slice
 * (`status`, `scored`, `blocker`, `intentional=only`) or says `open=0` starts with it off, so the link's filters are
 * the ones applied and it never lands on an empty list.
 *
 * A person who may score (the manager tier) also gets a Grid view of the same rows and filters (`RecordGrid`, "Pattern:
 * bulk edit grid"): Type, Priority, the Intentional flag and the three score levels as cells, saved one Pain Point at a
 * time. A Pain Point scored per persona shows its score cells locked, since one level cannot stand for several personas.
 *
 * The effective Pain Point type list (`projectPainPointApi.listTypes`) is loaded once here, because the type filter and
 * `PainPointFormModal`'s type picker both need it and loading it in the modal would flash on every open.
 *
 * Filters can be pre-set from the URL (a report figure links here, e.g. `?open=1&blocker=1`): `status`, `priority`,
 * `open=1|0` (still being worked; the default), `intentional=hide|only`, `blocker=1`, `scored=yes|no`, and `model` /
 * `rollup` (the scoring the report ran with). They are the page's filter state (the URL follows them), so the list
 * returns as left after visiting a record; each is a visible control that can be changed or cleared.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import type { Project } from "../../api/types";
import { api } from "../../api/client";
import { projectScoringApi, type ScoringScheme } from "../../api/scoring";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterPanel } from "../../components/FilterPanel";
import { FilterSelect } from "../../components/FilterSelect";
import { ListPageLayout } from "../../components/ListPageLayout";
import { RecordGrid } from "../../components/RecordGrid";
import { ScoringModelSwitcher } from "../../components/ScoringModelSwitcher";
import { SettingsPopoverButton } from "../../components/SettingsPopoverButton";
import { Spinner } from "../../components/Spinner";
import { ViewToggle, useViewMode } from "../../components/ViewToggle";
import { toErrorMessage } from "../../context/ToastContext";
import { useInitialSearchParams } from "../../hooks/useInitialSearchParams";
import { useOpenOnly } from "../../hooks/useOpenOnly";
import { useOptionalColumns } from "../../hooks/useOptionalColumns";
import { projectPainPointApi } from "./api";
import { PainPointFormModal } from "./PainPointFormModal";
import { BlockerBadge, PainPointScoreBadge } from "./PainPointScoreBadges";
import {
  PAIN_POINT_OPEN_STATUSES, PAIN_POINT_PRIORITY_LABEL, PAIN_POINT_ROLLUP_LABEL, PAIN_POINT_STATUS_LABEL, PAIN_POINT_STATUS_TONE,
} from "./types";
import type {
  EffectivePainPointType, PainPoint, PainPointFieldValues, PainPointPriority, PainPointRollup,
  PainPointScoringList, PainPointScoringSummary, PainPointScoringTargets, PainPointStatus, PainPointSubmissionSettings,
} from "./types";
import { Badge } from "../../components/Badge";
import { RecordCode } from "../../components/RecordCode";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
import { useCreatedToast } from "../../hooks/useCreatedToast";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useUrlChoice, useUrlFlag, useUrlText } from "../../hooks/useUrlFilter";
import { addSortParams, useListSort } from "../../hooks/useListSort";
import { SortField } from "../../components/SortField";
import { sortRows } from "../../utils/sortRows";
import { PAIN_POINT_SORT_KEYS, PAIN_POINT_SORT_VALUES } from "./contextStrategySort";
import { rowProjectId } from "../../api/projectScope";
import { ProjectScopeFilter } from "../../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../../components/ProjectScopeLabel";
import { useProjectScope } from "../../hooks/useProjectScope";
import { useTagFilter } from "../../hooks/useTagFilter";
import { TagFilterField } from "../../components/TagFilterField";
import { addSharedListFilters } from "../../utils/listFilterParams";
import { useStrings } from "../../context/TerminologyContext";
import { labelOptions } from "../../utils/labelOptions";

const SCHEME_KEY = "pain_point";
const DEFAULT_ROLLUP: PainPointRollup = "weighted_average";
const INTENTIONAL_FILTERS = ["hide", "only"] as const;
const SCORED_FILTERS = ["yes", "no"] as const;

export function ProjectPainPointsPage() {
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const commitQuickLinks = useCommitQuickLinks(projectId ?? "", "pain_point");
  const commitTags = useCommitTags(projectId ?? "", "pain_point");
  const announceCreated = useCreatedToast(projectId ?? "", "pain_point");
  const initial = useInitialSearchParams();
  const [project, setProject] = useState<Project | null>(null);
  // Where the grid puts its Columns / Discard / Save controls: the row of the view toggle.
  const [toolbarHost, setToolbarHost] = useState<HTMLElement | null>(null);
  const [painPoints, setPainPoints] = useState<PainPoint[] | null>(null);
  const [types, setTypes] = useState<EffectivePainPointType[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Who may submit here; until it loads (or if it fails) the New button is offered and the server decides.
  const [submission, setSubmission] = useState<PainPointSubmissionSettings | null>(null);

  const [search, setSearch] = useUrlText("q");
  const [statusFilter, setStatusFilter] = useUrlChoice("status", Object.keys(PAIN_POINT_STATUS_LABEL) as PainPointStatus[]);
  const [priorityFilter, setPriorityFilter] = useUrlChoice("priority", Object.keys(PAIN_POINT_PRIORITY_LABEL) as PainPointPriority[]);
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);
  const [intentional, setIntentional] = useUrlChoice("intentional", INTENTIONAL_FILTERS);
  const hideIntentional = intentional === "hide";
  const onlyIntentional = intentional === "only";
  const [openOnly, setOpenOnly] = useOpenOnly(
    initial, Object.keys(PAIN_POINT_STATUS_LABEL),
    ["yes", "no"].includes(initial.get("scored") ?? "") || initial.get("blocker") === "1" || initial.get("intentional") === "only",
  );
  const [blockersOnly, setBlockersOnly] = useUrlFlag("blocker");
  const [scoredFilter, setScoredFilter] = useUrlChoice("scored", SCORED_FILTERS);

  const [scheme, setScheme] = useState<ScoringScheme | null>(null);
  const [scoringTargets, setScoringTargets] = useState<PainPointScoringTargets | null>(null);
  // The scoring model and roll-up shown in this view; no `model` parameter means the scheme's default.
  const [modelParam, setModelParam] = useUrlText("model");
  const [rollupParam, setRollupParam] = useUrlChoice("rollup", Object.keys(PAIN_POINT_ROLLUP_LABEL) as PainPointRollup[]);
  const rollup = rollupParam || DEFAULT_ROLLUP;
  const [scoring, setScoring] = useState<PainPointScoringList | null>(null);
  const listSort = useListSort("pain_points", PAIN_POINT_SORT_KEYS, "code");

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useViewMode("context_strategy.pain_points", "list");
  // Bumped after the grid saves, so the list view's scores are read again when the person switches back.
  const [scoresVersion, setScoresVersion] = useState(0);

  async function reloadPainPoints() {
    if (!projectId) return;
    try {
      setPainPoints(await projectPainPointApi.list(projectId, { include_archived: includeArchived, ...tagFilter.listFilters, project_scope: projectScope.scope }));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "The Context & Strategy module is not enabled for this project's organisation, or you do not have access to it."));
    }
  }

  useEffect(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then(setProject);
    void projectPainPointApi.listTypes(projectId).then(setTypes).catch(() => setTypes([]));
    void projectPainPointApi.getSubmissionSettings(projectId).then(setSubmission).catch(() => setSubmission(null));
  }, [projectId]);

  useLoadOnChange(reloadPainPoints, [projectId, includeArchived, tagFilter.query, projectScope.scope]);

  useEffect(() => {
    if (!projectId) return;
    void projectScoringApi.get(projectId, SCHEME_KEY).then(setScheme).catch(() => setScheme(null));
    // Whether the create form may offer scoring; a failure just leaves the section out.
    void projectPainPointApi.getScoringTargets(projectId).then(setScoringTargets).catch(() => setScoringTargets(null));
  }, [projectId]);

  // Scores are secondary to the list itself: a failure here just leaves the
  // score columns empty rather than hiding the Pain Points.
  useEffect(() => {
    if (!projectId) return;
    projectPainPointApi
      .listScores(projectId, { model_key: modelParam || undefined, rollup, include_archived: includeArchived })
      .then(setScoring)
      .catch(() => setScoring(null));
  }, [projectId, modelParam, rollup, includeArchived, scoresVersion]);
  const model = modelParam || scoring?.model_key || null;

  const summaryById = new Map<string, PainPointScoringSummary>((scoring?.items ?? []).map((i) => [i.pain_point_id, i]));
  const scoreOf = (p: PainPoint) => summaryById.get(p.id)?.score?.normalised ?? null;

  const scoreSettingsLabel = scheme && model
    ? `Score settings: ${scheme.models.find((m) => m.key === model)?.label ?? model}, combined by ${PAIN_POINT_ROLLUP_LABEL[rollup]}`
    : "Score settings";

  const columns: DirectoryColumn<PainPoint>[] = [
    {
      key: "title", label: "Title", sortable: true,
      render: (p) => (
        <>
          {p.title}
          <ProjectScopeLabel row={p} />
          {p.is_intentional && <Badge tone="info" className="badge-after">Intentional</Badge>}
          {summaryById.get(p.id) && <BlockerBadge summary={summaryById.get(p.id)!} className="badge-after" />}
        </>
      ),
    },
    { key: "code", label: "Code", sortable: true, render: (p) => <RecordCode code={p.unique_code} ownerProjectCode={p.from_project_code} /> },
    { key: "type", label: "Type", sortable: true, optional: true, render: (p) => p.pain_point_type_name },
    { key: "priority", label: "Priority", sortable: true, optional: true, render: (p) => PAIN_POINT_PRIORITY_LABEL[p.priority] },
    {
      key: "status", label: "Status", sortable: true,
      render: (p) => <Badge tone={PAIN_POINT_STATUS_TONE[p.status]}>{PAIN_POINT_STATUS_LABEL[p.status]}</Badge>,
    },
    {
      key: "score", label: "Score", sortable: true, optional: true,
      headerAction: scheme && model && (
        <SettingsPopoverButton
          label={scoreSettingsLabel} title="Score settings"
          marked={model !== scheme.default_model_key || rollup !== DEFAULT_ROLLUP}
        >
          <div className="stack">
            <ScoringModelSwitcher
              models={scheme.models
                .filter((m) => !scheme.enabled_model_keys?.length || scheme.enabled_model_keys.includes(m.key) || m.key === model)
                .map((m) => ({ value: m.key, label: m.label }))}
              model={model}
              onModelChange={(next) => setModelParam(next === scheme.default_model_key ? "" : next)}
              rollups={Object.entries(PAIN_POINT_ROLLUP_LABEL).map(([value, label]) => ({ value, label }))}
              rollup={rollup}
              onRollupChange={(next) => setRollupParam(next === DEFAULT_ROLLUP ? "" : (next as PainPointRollup))}
            />
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>
              Applies to this view only; it is not saved.
            </span>
          </div>
        </SettingsPopoverButton>
      ),
      render: (p) => {
        const summary = summaryById.get(p.id);
        if (!summary) return "–";
        return <PainPointScoreBadge score={summary.score} />;
      },
    },
  ];

  const shown = useOptionalColumns("context_pain_points", columns);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (painPoints === null || project === null) return <Spinner />;

  /** The list's filters by the names its export takes; the server applies the same rules the page does. */
  function filterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    if (priorityFilter) params.set("priority", priorityFilter);
    if (search) params.set("search", search);
    if (includeArchived) params.set("include_archived", "true");
    if (openOnly) params.set("open_only", "true");
    if (hideIntentional) params.set("hide_intentional", "true");
    if (onlyIntentional) params.set("only_intentional", "true");
    if (blockersOnly) params.set("blockers_only", "true");
    if (scoredFilter) params.set("scored", scoredFilter);
    if (blockersOnly || scoredFilter) {
      if (modelParam) params.set("model_key", modelParam);
      params.set("rollup", rollup);
    }
    addSharedListFilters(params, tagFilter, projectScope);
    addSortParams(params, listSort.sort);
    return params;
  }

  const matches = (p: PainPoint, applyOpenOnly: boolean) => {
    if (hideIntentional && p.is_intentional) return false;
    if (onlyIntentional && !p.is_intentional) return false;
    if (applyOpenOnly && !PAIN_POINT_OPEN_STATUSES.includes(p.status)) return false;
    if (blockersOnly && !summaryById.get(p.id)?.is_blocker) return false;
    if (scoredFilter && (scoreOf(p) !== null) !== (scoredFilter === "yes")) return false;
    if (statusFilter && p.status !== statusFilter) return false;
    if (priorityFilter && p.priority !== priorityFilter) return false;
    if (search && !`${p.unique_code} ${p.title}`.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  };
  const filtered = painPoints.filter((p) => matches(p, openOnly));
  // An empty list the "Open only" default caused says so, so it is not read as "nothing recorded".
  const emptyBecauseOfOpenOnly = openOnly && filtered.length === 0 && painPoints.some((p) => matches(p, false));

  // Unscored items always sort last, in either direction.
  const rows = listSort.sort.key === "score"
    ? [...filtered].sort((a, b) => {
        const [x, y] = [scoreOf(a), scoreOf(b)];
        if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
        return listSort.sort.direction === "asc" ? x - y : y - x;
      })
    : sortRows(filtered, listSort.sort, PAIN_POINT_SORT_VALUES);

  // Scoring is the manager tier, and so is editing a Pain Point: the same grant opens the grid.
  const canScore = scoringTargets?.can_score === true;
  return (
    <div className="container stack">
      <ListPageLayout
        title="Pain Point"
        records={{ projectId, recordType: "pain_point", filters: filterParams().toString(), onImported: reloadPainPoints }}
        columnChooser={canScore && viewMode === "grid" ? null : shown.chooser}
        actions={
          submission && !submission.can_submit ? (
            <p className="text-muted" role="note">{submission.restriction_message}</p>
          ) : (
            <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
              New Pain Point
            </button>
          )
        }
        filter={
          <FilterPanel
            sectionKey="context_strategy.pain_points.list" total={filtered.length}
            search={search} onSearchChange={setSearch} searchPlaceholder="Search Pain Points…" searchAriaLabel="Search Pain Points"
          >
            <FilterSelect
              label={strings.filters.status}
              value={statusFilter}
              onChange={setStatusFilter}
              allLabel="All statuses"
              options={labelOptions(PAIN_POINT_STATUS_LABEL)}
            />
            <FilterSelect
              label={strings.filters.priority}
              value={priorityFilter}
              onChange={setPriorityFilter}
              allLabel="All priorities"
              options={labelOptions(PAIN_POINT_PRIORITY_LABEL)}
            />
            <FilterSelect
              label={strings.filters.scoring}
              value={scoredFilter}
              onChange={setScoredFilter}
              allLabel="Any scoring"
              options={[{ value: "yes", label: "Scored" }, { value: "no", label: "Not scored" }]}
            />
            <FilterCheckbox label="Open only" checked={openOnly} onChange={setOpenOnly} />
            <FilterCheckbox label="Blockers only" checked={blockersOnly} onChange={setBlockersOnly} />
            <FilterCheckbox
              label="Hide intentional limitations" checked={hideIntentional}
              onChange={(next) => setIntentional(next ? "hide" : "")}
            />
            <FilterCheckbox
              label="Only intentional limitations" checked={onlyIntentional}
              onChange={(next) => setIntentional(next ? "only" : "")}
            />
            <ProjectScopeFilter scope={projectScope} />
            {projectId && <TagFilterField projectId={projectId} filter={tagFilter} />}
            <SortField list={listSort} columns={columns} />
            <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
          </FilterPanel>
        }
      >
          {canScore && (
            <div className="row" style={{ justifyContent: "flex-end", alignItems: "center" }}>
              <div ref={setToolbarHost} className="row" style={{ alignItems: "center" }} />
              <ViewToggle mode={viewMode} onChange={setViewMode} showTilesOption={false} showGridOption />
            </div>
          )}
          {canScore && viewMode === "grid" ? (
            <RecordGrid
              projectId={projectId} toolbarHost={toolbarHost} recordType="pain_point" filters={filterParams().toString()} contextKeys={["title"]}
              recordHref={(row) => `/projects/${row.project_id ?? projectId}/modules/context_strategy/pain-points/${row.id}`}
              onSaved={() => { setScoresVersion((n) => n + 1); void reloadPainPoints(); }}
            />
          ) : (
          <DirectoryTable
            ariaLabel="Pain Points"
            columns={shown.columns}
            rows={rows}
            sort={listSort.sort}
            onSort={listSort.onHeaderSort}
            rowKey={(p) => p.id}
            placements={{ projectId, artefactType: "pain_point", rowId: (p) => p.id }}
            onRowClick={(p) => navigate(`/projects/${rowProjectId(p, projectId)}/modules/context_strategy/pain-points/${p.id}`)}
            emptyState={
              <p className="text-muted">
                {emptyBecauseOfOpenOnly
                  ? "No open Pain Points. Untick Open only to include rejected, duplicate, addressed and closed ones."
                  : painPoints.length > 0
                    ? "No Pain Points match these filters."
                    : "No Pain Points recorded for this project yet."}
              </p>
            }
          />
          )}
      </ListPageLayout>

      {creating && (
        <PainPointFormModal
          projectId={projectId}
          types={types}
          scoring={scheme && scoringTargets?.can_score ? { scheme, targets: scoringTargets.available_targets } : undefined}
          error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={async (values: PainPointFieldValues, quickLinks, tags) => {
            setCreateError(null);
            try {
              const created = await projectPainPointApi.create(projectId, values);
              announceCreated("Pain Point", created);
              setCreating(false);
              await commitQuickLinks(created.id, quickLinks);
              await commitTags(created.id, tags);
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
