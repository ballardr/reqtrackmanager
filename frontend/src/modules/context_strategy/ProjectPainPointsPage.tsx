/**
 * Module: modules/context_strategy/ProjectPainPointsPage
 *
 * The Context & Strategy module's project-scoped Pain Point list route,
 * mounted at
 * `/projects/:projectId/modules/context_strategy/pain-points`, reached via
 * this module's third top-level nav-rail entry. Mirrors
 * `ProjectStrategiesPage.tsx`'s exact `DirectoryTable` + `FilterPanel` +
 * "New X" `Modal` shape — Pain Point is project-scoped only (§6), so unlike that page there is no org-scoped sibling panel.
 *
 * Per-persona scoring shows in the list: a Score column (the
 * roll-up under the model and persona roll-up picked in the gear on the
 * column header, "chosen when viewing") and a Blocker badge after the title
 * that stays visible whichever is chosen. The Score column is sortable, so
 * switching model re-ranks the list. Intentional limitations carry an
 * "Intentional" badge and can be hidden from the list via a filter.
 *
 * The list opens on open Pain Points only (the "Open only" filter is ticked
 * and stays visible). A link that names a slice (`status`, `scored`,
 * `blocker`, `intentional=only`) or says `open=0` starts with it off, so the
 * filters in the link are the ones applied and a link never lands on an empty
 * list.
 *
 * Also loads this project's effective Pain Point type list
 * (`projectPainPointApi.listTypes`) once, up front — both the type filter
 * dropdown and `PainPointFormModal`'s own type picker need it, and loading
 * it here (rather than inside the modal) avoids a load flash every time the
 * "New Pain Point" modal opens.
 *
 * Filters can be pre-set from the URL (a report figure links here, e.g.
 * `?open=1&blocker=1`): `status`, `priority`, `open=1|0` (still being worked; the default),
 * `intentional=hide|only`, `blocker=1`, `scored=yes|no`, and `model` /
 * `rollup` (the scoring the report ran with). They are the page's filter state (the URL is kept up to
 * date as they change), so the list comes back as it was left after a visit to a record; each is a
 * visible control in the filter panel, so it can be changed or cleared.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import type { Project } from "../../api/types";
import { api } from "../../api/client";
import { projectScoringApi, type ScoringScheme } from "../../api/scoring";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { ListPageLayout } from "../../components/ListPageLayout";
import { ScoringModelSwitcher } from "../../components/ScoringModelSwitcher";
import { SettingsPopoverButton } from "../../components/SettingsPopoverButton";
import { Spinner } from "../../components/Spinner";
import { cycleSort } from "../../components/sortState";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useInitialSearchParams } from "../../hooks/useInitialSearchParams";
import { useOpenOnly } from "../../hooks/useOpenOnly";
import { projectPainPointApi } from "./api";
import { PainPointFormModal } from "./PainPointFormModal";
import { BlockerBadge, PainPointScoreBadge } from "./PainPointScoreBadges";
import {
  PAIN_POINT_OPEN_STATUSES, PAIN_POINT_PRIORITY_LABEL, PAIN_POINT_ROLLUP_LABEL, PAIN_POINT_STATUS_LABEL, PAIN_POINT_STATUS_TONE,
} from "./types";
import type {
  EffectivePainPointType, PainPoint, PainPointFieldValues, PainPointPriority, PainPointRollup,
  PainPointScoringList, PainPointScoringSummary, PainPointScoringTargets, PainPointStatus,
} from "./types";
import { Badge } from "../../components/Badge";
import { RecordCode } from "../../components/RecordCode";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useUrlChoice, useUrlFlag, useUrlSort, useUrlText } from "../../hooks/useUrlFilter";
import { rowProjectId } from "../../api/projectScope";
import { ProjectScopeFilter } from "../../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../../components/ProjectScopeLabel";
import { useProjectScope } from "../../hooks/useProjectScope";
import { useTagFilter } from "../../hooks/useTagFilter";
import { TagFilterField } from "../../components/TagFilterField";
import { addSharedListFilters } from "../../utils/listFilterParams";

const SCHEME_KEY = "pain_point";
const DEFAULT_ROLLUP: PainPointRollup = "weighted_average";
const INTENTIONAL_FILTERS = ["hide", "only"] as const;
const SCORED_FILTERS = ["yes", "no"] as const;
const SORT_KEYS = ["score"] as const;

export function ProjectPainPointsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const commitQuickLinks = useCommitQuickLinks(projectId ?? "", "pain_point");
  const commitTags = useCommitTags(projectId ?? "", "pain_point");
  const initial = useInitialSearchParams();
  const [project, setProject] = useState<Project | null>(null);
  const [painPoints, setPainPoints] = useState<PainPoint[] | null>(null);
  const [types, setTypes] = useState<EffectivePainPointType[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

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
  const [sort, setSort] = useUrlSort<string>(SORT_KEYS);

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function reloadPainPoints() {
    if (!projectId) return;
    try {
      setPainPoints(await projectPainPointApi.list(projectId, { include_archived: includeArchived, tags: tagFilter.tags, tag_mode: tagFilter.mode, project_scope: projectScope.scope }));
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
  }, [projectId, modelParam, rollup, includeArchived]);
  const model = modelParam || scoring?.model_key || null;

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
    return params;
  }

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (painPoints === null || project === null) return <Spinner />;

  const summaryById = new Map<string, PainPointScoringSummary>((scoring?.items ?? []).map((i) => [i.pain_point_id, i]));
  const scoreOf = (p: PainPoint) => summaryById.get(p.id)?.score?.normalised ?? null;

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
  const rows = sort?.key === "score"
    ? [...filtered].sort((a, b) => {
        const [x, y] = [scoreOf(a), scoreOf(b)];
        if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
        return sort.direction === "asc" ? x - y : y - x;
      })
    : filtered;

  const scoreSettingsLabel = scheme && model
    ? `Score settings: ${scheme.models.find((m) => m.key === model)?.label ?? model}, combined by ${PAIN_POINT_ROLLUP_LABEL[rollup]}`
    : "Score settings";

  const columns: DirectoryColumn<PainPoint>[] = [
    {
      key: "title", label: "Title",
      render: (p) => (
        <>
          {p.title}
          <ProjectScopeLabel row={p} />
          {p.is_intentional && <Badge tone="info" className="badge-after">Intentional</Badge>}
          {summaryById.get(p.id) && <BlockerBadge summary={summaryById.get(p.id)!} className="badge-after" />}
        </>
      ),
    },
    { key: "code", label: "Code", render: (p) => <RecordCode code={p.unique_code} ownerProjectCode={p.from_project_code} /> },
    { key: "type", label: "Type", render: (p) => p.pain_point_type_name },
    { key: "priority", label: "Priority", render: (p) => PAIN_POINT_PRIORITY_LABEL[p.priority] },
    {
      key: "status", label: "Status",
      render: (p) => <Badge tone={PAIN_POINT_STATUS_TONE[p.status]}>{PAIN_POINT_STATUS_LABEL[p.status]}</Badge>,
    },
    {
      key: "score", label: "Score", sortable: true,
      headerAction: scheme && model && (
        <SettingsPopoverButton
          label={scoreSettingsLabel} title="Score settings"
          marked={model !== scheme.default_model_key || rollup !== DEFAULT_ROLLUP}
        >
          <div className="stack">
            <ScoringModelSwitcher
              models={scheme.models.map((m) => ({ value: m.key, label: m.label }))}
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

  return (
    <div className="container stack">
      <ListPageLayout
        title="Pain Point"
        records={{ projectId, recordType: "pain_point", filters: filterParams().toString(), onImported: reloadPainPoints }}
        actions={
          <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
            New Pain Point
          </button>
        }
        filter={
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
              onChange={(next) => setIntentional(next ? "hide" : "")}
            />
            <FilterCheckbox
              label="Only intentional limitations" checked={onlyIntentional}
              onChange={(next) => setIntentional(next ? "only" : "")}
            />
            <ProjectScopeFilter scope={projectScope} />
            {projectId && <TagFilterField projectId={projectId} filter={tagFilter} />}
            <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
          </FilterPanel>
        }
      >
          <DirectoryTable
            ariaLabel="Pain Points"
            columns={columns}
            rows={rows}
            sort={sort}
            onSort={(key) => setSort((current) => cycleSort(current, key))}
            rowKey={(p) => p.id}
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
              showToast("Pain Point created.");
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
