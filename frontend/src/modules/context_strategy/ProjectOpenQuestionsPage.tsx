/**
 * Module: modules/context_strategy/ProjectOpenQuestionsPage
 *
 * The Context & Strategy module's project-scoped Open Question list route,
 * mounted at
 * `/projects/:projectId/modules/context_strategy/open-questions`, reached
 * via this module's fifth and last top-level nav-rail entry.
 * Mirrors `ProjectPainPointsPage.tsx`'s exact `DirectoryTable` + `FilterPanel`
 * + "New X" `Modal` shape — Open Question is project-scoped only (source
 * overview §9), so unlike `ProjectStrategiesPage.tsx`/
 * `ProjectGuidingPrinciplesPage.tsx` there is no org-scoped sibling panel,
 * and unlike `ProjectPainPointsPage.tsx` there is no type vocabulary to load
 * up front either — the simplest of the five list pages this module ships.
 *
 * The list column shows `question` itself, not a separate `title` — Open
 * Question has no `title` field (see `types.ts`'s own docstring).
 *
 * The list opens on unresolved Open Questions only (the "Open only" filter is
 * ticked and stays visible); a link with a valid `status`, or `open=0`, starts
 * with it off (`hooks/useOpenOnly.ts`).
 *
 * Filters can be pre-set from the URL (a report figure links here, e.g.
 * `?open=1&overdue=1`): `status`, `priority`, `open=1|0` (unresolved; the
 * default), `overdue=1` (due date passed) and `unowned=1`. They only seed the
 * state; each is a visible control in the filter panel.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import type { Project } from "../../api/types";
import { api } from "../../api/client";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { ListPageLayout } from "../../components/ListPageLayout";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useInitialSearchParams } from "../../hooks/useInitialSearchParams";
import { useOpenOnly } from "../../hooks/useOpenOnly";
import { projectOpenQuestionApi } from "./api";
import { OpenQuestionFormModal } from "./OpenQuestionFormModal";
import { OPEN_QUESTION_OPEN_STATUSES, OPEN_QUESTION_PRIORITY_LABEL, OPEN_QUESTION_STATUS_LABEL, OPEN_QUESTION_STATUS_TONE } from "./types";
import type { OpenQuestion, OpenQuestionFieldValues, OpenQuestionPriority, OpenQuestionStatus } from "./types";
import { Badge } from "../../components/Badge";
import { RecordCode } from "../../components/RecordCode";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useUrlChoice, useUrlFlag, useUrlText } from "../../hooks/useUrlFilter";
import { rowProjectId } from "../../api/projectScope";
import { ProjectScopeFilter } from "../../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../../components/ProjectScopeLabel";
import { useProjectScope } from "../../hooks/useProjectScope";
import { localToday } from "../../utils/localDate";
import { useTagFilter } from "../../hooks/useTagFilter";
import { TagFilterField } from "../../components/TagFilterField";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
import { addSharedListFilters } from "../../utils/listFilterParams";

export function ProjectOpenQuestionsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const commitQuickLinks = useCommitQuickLinks(projectId ?? "", "open_question");
  const commitTags = useCommitTags(projectId ?? "", "open_question");
  const initial = useInitialSearchParams();
  const [project, setProject] = useState<Project | null>(null);
  const [openQuestions, setOpenQuestions] = useState<OpenQuestion[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Filters live in the URL so the list comes back as it was left after a visit to a record.
  const [search, setSearch] = useUrlText("q");
  const [statusFilter, setStatusFilter] = useUrlChoice("status", Object.keys(OPEN_QUESTION_STATUS_LABEL) as OpenQuestionStatus[]);
  const [priorityFilter, setPriorityFilter] = useUrlChoice("priority", Object.keys(OPEN_QUESTION_PRIORITY_LABEL) as OpenQuestionPriority[]);
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);
  const [openOnly, setOpenOnly] = useOpenOnly(initial, Object.keys(OPEN_QUESTION_STATUS_LABEL));
  const [overdueOnly, setOverdueOnly] = useUrlFlag("overdue");
  const [unownedOnly, setUnownedOnly] = useUrlFlag("unowned");

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function reloadOpenQuestions() {
    if (!projectId) return;
    try {
      setOpenQuestions(await projectOpenQuestionApi.list(projectId, { include_archived: includeArchived, tags: tagFilter.tags, tag_mode: tagFilter.mode, project_scope: projectScope.scope }));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "The Context & Strategy module isn't enabled for this project's organisation, or you don't have access to it."));
    }
  }

  useEffect(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then(setProject);
  }, [projectId]);

  useLoadOnChange(reloadOpenQuestions, [projectId, includeArchived, tagFilter.query, projectScope.scope]);

  /** The list's filters by the names its export takes; the server applies the same rules the page does. */
  function filterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    if (priorityFilter) params.set("priority", priorityFilter);
    if (search) params.set("search", search);
    if (includeArchived) params.set("include_archived", "true");
    if (openOnly) params.set("open_only", "true");
    if (overdueOnly) params.set("overdue_only", "true");
    if (unownedOnly) params.set("unowned_only", "true");
    addSharedListFilters(params, tagFilter, projectScope);
    return params;
  }

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (openQuestions === null || project === null) return <Spinner />;

  const today = localToday(); // the person's own day, as the export's filter reads it
  const matches = (q: OpenQuestion, applyOpenOnly: boolean) => {
    if (applyOpenOnly && !OPEN_QUESTION_OPEN_STATUSES.includes(q.status)) return false;
    if (overdueOnly && !(q.due_date !== null && q.due_date < today)) return false;
    if (unownedOnly && q.owner !== null) return false;
    if (statusFilter && q.status !== statusFilter) return false;
    if (priorityFilter && q.priority !== priorityFilter) return false;
    if (search && !`${q.unique_code} ${q.question}`.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  };
  const filtered = openQuestions.filter((q) => matches(q, openOnly));
  // An empty list the "Open only" default caused says so, so it is not read as "nothing recorded".
  const emptyBecauseOfOpenOnly = openOnly && filtered.length === 0 && openQuestions.some((q) => matches(q, false));

  const columns: DirectoryColumn<OpenQuestion>[] = [
    { key: "question", label: "Question", render: (q) => <>{q.question}<ProjectScopeLabel row={q} /></> },
    { key: "code", label: "Code", render: (q) => <RecordCode code={q.unique_code} ownerProjectCode={q.from_project_code} /> },
    { key: "priority", label: "Priority", render: (q) => OPEN_QUESTION_PRIORITY_LABEL[q.priority] },
    {
      key: "status", label: "Status",
      render: (q) => <Badge tone={OPEN_QUESTION_STATUS_TONE[q.status]}>{OPEN_QUESTION_STATUS_LABEL[q.status]}</Badge>,
    },
    { key: "due_date", label: "Due", render: (q) => q.due_date ?? "—" },
  ];

  return (
    <div className="container stack">
      <ListPageLayout
        title="Open Question"
        records={{ projectId, recordType: "open_question", filters: filterParams().toString(), onImported: reloadOpenQuestions }}
        actions={
          <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
            New Open Question
          </button>
        }
        filter={
          <FilterPanel
            sectionKey="context_strategy.open_questions.list" total={filtered.length}
            search={search} onSearchChange={setSearch} searchPlaceholder="Search Open Questions…" searchAriaLabel="Search Open Questions"
          >
            <FilterField label="Status">
              <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as OpenQuestionStatus | "")}>
                <option value="">All statuses</option>
                {Object.entries(OPEN_QUESTION_STATUS_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </FilterField>
            <FilterField label="Priority">
              <select className="input" value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value as OpenQuestionPriority | "")}>
                <option value="">All priorities</option>
                {Object.entries(OPEN_QUESTION_PRIORITY_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </FilterField>
            <FilterCheckbox label="Open only" checked={openOnly} onChange={setOpenOnly} />
            <FilterCheckbox label="Overdue only" checked={overdueOnly} onChange={setOverdueOnly} />
            <FilterCheckbox label="Unowned only" checked={unownedOnly} onChange={setUnownedOnly} />
            <ProjectScopeFilter scope={projectScope} />
            {projectId && <TagFilterField projectId={projectId} filter={tagFilter} />}
            <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
          </FilterPanel>
        }
      >
        <DirectoryTable
          ariaLabel="Open Questions"
          columns={columns}
          rows={filtered}
          rowKey={(q) => q.id}
          onRowClick={(q) => navigate(`/projects/${rowProjectId(q, projectId)}/modules/context_strategy/open-questions/${q.id}`)}
          emptyState={
            <p className="text-muted">
              {emptyBecauseOfOpenOnly
                ? "No open Open Questions. Untick Open only to include resolved and withdrawn ones."
                : openQuestions.length > 0
                  ? "No Open Questions match these filters."
                  : "No Open Questions recorded for this project yet."}
            </p>
          }
        />
      </ListPageLayout>

      {creating && (
        <OpenQuestionFormModal
          projectId={projectId}
          error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={async (values: OpenQuestionFieldValues, quickLinks, tags) => {
            setCreateError(null);
            try {
              const created = await projectOpenQuestionApi.create(projectId, values);
              showToast("Open Question created.");
              setCreating(false);
              await commitQuickLinks(created.id, quickLinks);
              await commitTags(created.id, tags);
              await reloadOpenQuestions();
            } catch (err) {
              setCreateError(toErrorMessage(err, "Could not create Open Question."));
            }
          }}
        />
      )}
    </div>
  );
}
