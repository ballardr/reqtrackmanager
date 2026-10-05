/**
 * Module: modules/context_strategy/ProjectOpenQuestionsPage
 *
 * The Context & Strategy module's project-scoped Open Question list route
 * (docs/plans/module-01-context-and-strategy-plan.md Phase 7.5), mounted at
 * `/projects/:projectId/modules/context_strategy/open-questions`, reached
 * via this module's fifth and last top-level nav-rail entry (Phase 0 Q7).
 * Mirrors `ProjectPainPointsPage.tsx`'s exact `DirectoryTable` + `FilterPanel`
 * + "New X" `Modal` shape — Open Question is project-scoped only (source
 * overview §9), so unlike `ProjectStrategiesPage.tsx`/
 * `ProjectGuidingPrinciplesPage.tsx` there is no org-scoped sibling panel,
 * and unlike `ProjectPainPointsPage.tsx` there is no type vocabulary to load
 * up front either — the simplest of the five list pages this module ships.
 *
 * The list column shows `question` itself, not a separate `title` — Open
 * Question has no `title` field (see `types.ts`'s own docstring).
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import type { Project } from "../../api/types";
import { api } from "../../api/client";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectOpenQuestionApi } from "./api";
import { OpenQuestionFormModal } from "./OpenQuestionFormModal";
import { OPEN_QUESTION_PRIORITY_LABEL, OPEN_QUESTION_STATUS_LABEL, OPEN_QUESTION_STATUS_TONE } from "./types";
import type { OpenQuestion, OpenQuestionFieldValues, OpenQuestionPriority, OpenQuestionStatus } from "./types";

export function ProjectOpenQuestionsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [project, setProject] = useState<Project | null>(null);
  const [openQuestions, setOpenQuestions] = useState<OpenQuestion[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<OpenQuestionStatus | "">("");
  const [priorityFilter, setPriorityFilter] = useState<OpenQuestionPriority | "">("");
  const [includeArchived, setIncludeArchived] = useState(false);

  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function reloadOpenQuestions() {
    if (!projectId) return;
    try {
      setOpenQuestions(await projectOpenQuestionApi.list(projectId, { include_archived: includeArchived }));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "The Context & Strategy module isn't enabled for this project's organisation, or you don't have access to it."));
    }
  }

  useEffect(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then(setProject);
  }, [projectId]);

  useEffect(() => {
    void reloadOpenQuestions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, includeArchived]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (openQuestions === null || project === null) return <Spinner />;

  const filtered = openQuestions.filter((q) => {
    if (statusFilter && q.status !== statusFilter) return false;
    if (priorityFilter && q.priority !== priorityFilter) return false;
    if (search && !q.question.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const columns: DirectoryColumn<OpenQuestion>[] = [
    { key: "question", label: "Question", render: (q) => q.question },
    { key: "priority", label: "Priority", render: (q) => OPEN_QUESTION_PRIORITY_LABEL[q.priority] },
    {
      key: "status", label: "Status",
      render: (q) => <span className={`badge badge--${OPEN_QUESTION_STATUS_TONE[q.status]}`}>{OPEN_QUESTION_STATUS_LABEL[q.status]}</span>,
    },
    { key: "due_date", label: "Due", render: (q) => q.due_date ?? "—" },
  ];

  return (
    <div className="container stack">
      <h1 style={{ margin: 0 }}>Open Question</h1>
      <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
        New Open Question
      </button>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel="Open Questions"
          columns={columns}
          rows={filtered}
          rowKey={(q) => q.id}
          onRowClick={(q) => navigate(`/projects/${projectId}/modules/context_strategy/open-questions/${q.id}`)}
          emptyState={<p className="text-muted">No Open Questions recorded for this project yet.</p>}
        />
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
          <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
        </FilterPanel>
      </div>

      {creating && (
        <OpenQuestionFormModal
          error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={async (values: OpenQuestionFieldValues) => {
            setCreateError(null);
            try {
              await projectOpenQuestionApi.create(projectId, values);
              showToast("Open Question created.");
              setCreating(false);
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
