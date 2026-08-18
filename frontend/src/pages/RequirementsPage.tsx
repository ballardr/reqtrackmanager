import { ArrowDown, ArrowUp, GitPullRequest, MessageSquare, Plus, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  Category,
  Component,
  CustomFieldDefinition,
  OrgUser,
  Project,
  ProjectStage,
  Requirement,
  RequirementImportResult,
  RequirementLevel,
  RequirementStatus,
} from "../api/types";
import { REQUIREMENT_LEVEL_LABEL, REQUIREMENT_STATUS_LABEL } from "../api/types";
import { CsvImportWizard, type CsvImportWizardHandle } from "../components/CsvImportWizard";
import { CustomFieldsForm } from "../components/CustomFieldsForm";
import { FilterBadge } from "../components/FilterBadge";
import { FilterCheckbox, FilterField, FilterPanel } from "../components/FilterPanel";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { Popover } from "../components/Popover";
import { Spinner } from "../components/Spinner";
import { useViewMode, ViewToggle } from "../components/ViewToggle";
import { useAuth } from "../context/AuthContext";
import { useTerm, useTermPlural } from "../context/TerminologyContext";
import { useMyProjectRoles } from "../hooks/useMyProjectRoles";
import { t } from "../i18n/strings";

const strings = t();

const PAGE_SIZE = 30;

const STATUS_OPTIONS: RequirementStatus[] = ["draft", "reviewed", "approved", "completed", "archived"];

/**
 * Requirement browser (C-G-04: sorted by component/category), with search
 * by name/ID (U-E-01), a filter panel (status/target version/category/
 * comments/watched), scoping-stage-only reordering (C-E-03), and
 * incremental "load more" pagination (U-P-06) for large requirement sets.
 */
export function RequirementsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const { user } = useAuth();
  const myRoles = useMyProjectRoles(projectId);
  const [isOrgAdminOfProject, setIsOrgAdminOfProject] = useState(false);
  const canManageProject =
    myRoles.includes("project_manager") || myRoles.includes("project_administrator") || isOrgAdminOfProject;
  const [requirements, setRequirements] = useState<Requirement[] | null>(null);
  const [total, setTotal] = useState(0);
  const [components, setComponents] = useState<Component[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  // Both start empty before the first fetch resolves, which is
  // indistinguishable from "this project genuinely has none yet" — without
  // this flag, opening "New requirement" before that fetch completes
  // showed the quick-create-component/category inline form (meant only for
  // a genuinely empty project) at the same time as the real create form,
  // producing two ambiguous "Name" fields.
  const [metaLoaded, setMetaLoaded] = useState(false);
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [newInlineComponentName, setNewInlineComponentName] = useState("");
  const [newInlineComponentPrefix, setNewInlineComponentPrefix] = useState("");
  const [newInlineCategoryName, setNewInlineCategoryName] = useState("");
  const [newInlineCategoryPrefix, setNewInlineCategoryPrefix] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<RequirementStatus | "">("");
  const [targetStageFilter, setTargetStageFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [hasCommentsOnly, setHasCommentsOnly] = useState(false);
  const [onlyWatched, setOnlyWatched] = useState(false);
  const [showNewForm, setShowNewForm] = useState(false);
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const addTriggerRef = useRef<HTMLButtonElement>(null);
  const csvWizardRef = useRef<CsvImportWizardHandle>(null);
  const [newName, setNewName] = useState("");
  const [newReasoning, setNewReasoning] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newComponentId, setNewComponentId] = useState("");
  const [newCategoryId, setNewCategoryId] = useState("");
  const [newTargetStageId, setNewTargetStageId] = useState("");
  const [newLevel, setNewLevel] = useState<RequirementLevel>("requirement");
  const [customFieldDefs, setCustomFieldDefs] = useState<CustomFieldDefinition[]>([]);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});
  const requirementTerm = useTerm("requirement");
  const requirementsTerm = useTermPlural("requirement");
  const [viewMode, setViewMode] = useViewMode("requirements");
  const [importResult, setImportResult] = useState<RequirementImportResult | null>(null);
  const [importing, setImporting] = useState(false);
  const [project, setProject] = useState<Project | null>(null);

  function listParams(offset: number): URLSearchParams {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (search) params.set("search", search);
    if (statusFilter) params.set("status", statusFilter);
    if (targetStageFilter) params.set("target_stage_id", targetStageFilter);
    if (categoryFilter) params.set("category_id", categoryFilter);
    if (hasCommentsOnly) params.set("has_comments", "true");
    if (onlyWatched) params.set("only_watched", "true");
    return params;
  }

  async function loadRequirements(offset: number, append: boolean) {
    if (!projectId) return;
    const page = await api.getPage<Requirement>(
      `/api/v1/projects/${projectId}/requirements?${listParams(offset).toString()}`
    );
    setRequirements((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
  }

  async function reload() {
    if (!projectId) return;
    setRequirements(null);
    const [comps, cats, stgs, defs] = await Promise.all([
      api.get<Component[]>(`/api/v1/projects/${projectId}/components`),
      api.get<Category[]>(`/api/v1/projects/${projectId}/categories`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      api.get<CustomFieldDefinition[]>(`/api/v1/projects/${projectId}/custom-fields?entity_kind=requirement`),
      loadRequirements(0, false),
    ]);
    setComponents(comps);
    setCategories(cats);
    setStages(stgs);
    setCustomFieldDefs(defs);
    // Target is mandatory (it can never be left unset) — the select always
    // has a real stage pre-filled, never a blank "—" option, same as the
    // backend's own create-time default (routers/requirements.py).
    if (!newTargetStageId && stgs[0]) setNewTargetStageId(stgs[0].id);
    const selectedComponentId = newComponentId || comps[0]?.id || "";
    if (!newComponentId && comps[0]) setNewComponentId(comps[0].id);
    // Must belong to the selected component (the tree) — picking any
    // project-wide first category could silently mismatch it.
    if (!newCategoryId) {
      const firstOwnCategory = cats.find((c) => c.component_id === selectedComponentId);
      if (firstOwnCategory) setNewCategoryId(firstOwnCategory.id);
    }
    setMetaLoaded(true);
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, search, statusFilter, targetStageFilter, categoryFilter, hasCommentsOnly, onlyWatched]);

  // Deep-linked from the Project Overview page's "New requirement" button
  // (?new=1) — opened once, then the param is stripped so a later reload
  // of this page doesn't keep reopening the form.
  useEffect(() => {
    if (searchParams.get("new") === "1") {
      setShowNewForm(true);
      setSearchParams((params) => {
        params.delete("new");
        return params;
      }, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  useEffect(() => {
    if (!projectId || !user) return;
    (async () => {
      try {
        const proj = await api.get<Project>(`/api/v1/projects/${projectId}`);
        setProject(proj);
        const users = await api.get<OrgUser[]>(`/api/v1/orgs/${proj.organization_id}/users`);
        setIsOrgAdminOfProject(users.some((u) => u.user_id === user.id && u.roles.includes("org_admin")));
      } catch {
        // No org role at all (rare) — canManageProject still resolves correctly
        // from myRoles alone in that case.
      }
    })();
  }, [projectId, user]);

  async function createInlineComponent() {
    if (!projectId || !newInlineComponentName || !newInlineComponentPrefix) return;
    await api.post(`/api/v1/projects/${projectId}/components`, {
      name: newInlineComponentName,
      prefix: newInlineComponentPrefix,
    });
    setNewInlineComponentName("");
    setNewInlineComponentPrefix("");
    reload();
  }

  async function createInlineCategory() {
    if (!projectId || !newInlineCategoryName || !newInlineCategoryPrefix || !newComponentId) return;
    await api.post(`/api/v1/projects/${projectId}/categories`, {
      name: newInlineCategoryName,
      prefix: newInlineCategoryPrefix,
      component_id: newComponentId,
    });
    setNewInlineCategoryName("");
    setNewInlineCategoryPrefix("");
    reload();
  }

  async function createRequirement() {
    if (!projectId || !newComponentId || !newCategoryId || !newTargetStageId) return;
    await api.post(`/api/v1/projects/${projectId}/requirements`, {
      name: newName,
      reasoning: newReasoning,
      description: newDescription,
      component_id: newComponentId,
      category_id: newCategoryId,
      target_stage_id: newTargetStageId,
      level: newLevel,
      keywords: [],
      custom_fields: customFieldValues,
    });
    setNewName("");
    setNewReasoning("");
    setNewDescription("");
    setNewLevel("requirement");
    setCustomFieldValues({});
    setShowNewForm(false);
    reload();
  }

  async function importCsv(file: File) {
    if (!projectId) return;
    setImporting(true);
    try {
      const result = await api.postFile<RequirementImportResult>(
        `/api/v1/projects/${projectId}/requirements/import`, file
      );
      setImportResult(result);
      reload();
    } finally {
      setImporting(false);
    }
  }

  async function move(id: string, direction: "up" | "down") {
    await api.post(`/api/v1/projects/${projectId}/requirements/${id}/move`, { direction });
    reload();
  }

  function componentName(id: string) {
    return components.find((c) => c.id === id)?.name ?? "";
  }
  function categoryName(id: string) {
    return categories.find((c) => c.id === id)?.name ?? "";
  }
  function stageName(id: string | null) {
    return stages.find((s) => s.id === id)?.name ?? "—";
  }

  function toggleStatusFilter(status: RequirementStatus) {
    setStatusFilter((current) => (current === status ? "" : status));
  }

  function badges(r: Requirement) {
    return (
      <>
        {r.comment_count > 0 && (
          <span className="row" title={`${r.comment_count} comment(s)`} style={{ gap: "0.2rem" }}>
            <MessageSquare size={14} /> {r.comment_count}
          </span>
        )}
        {r.has_open_change_request && (
          <span title="Has a pending change request">
            <GitPullRequest size={14} />
          </span>
        )}
        {r.requires_approval && (
          <span title="Requires approval">
            <TriangleAlert size={14} />
          </span>
        )}
      </>
    );
  }

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>{requirementsTerm}</h1>
        <button ref={addTriggerRef} className="btn btn-primary" onClick={() => setAddMenuOpen((v) => !v)}>
          <Plus size={16} /> New {requirementTerm}
        </button>
        {addMenuOpen && (
          <Popover anchorRef={addTriggerRef} title={`New ${requirementTerm}`} onClose={() => setAddMenuOpen(false)}>
            <div className="stack" style={{ gap: "0.25rem", minWidth: 160 }}>
              <button
                className="btn"
                style={{ justifyContent: "flex-start" }}
                onClick={() => {
                  setShowNewForm(true);
                  setAddMenuOpen(false);
                }}
              >
                {strings.requirements.addOne}
              </button>
              <button
                className="btn"
                style={{ justifyContent: "flex-start" }}
                onClick={() => {
                  csvWizardRef.current?.openFilePicker();
                  setAddMenuOpen(false);
                }}
              >
                {strings.requirements.importFromCsv}
              </button>
            </div>
          </Popover>
        )}
      </div>

      <CsvImportWizard
        ref={csvWizardRef}
        showImportTrigger={false}
        projectId={projectId ?? ""} projectName={project?.name ?? ""}
        components={components} categories={categories} stages={stages} customFields={customFieldDefs}
        importing={importing} onImport={importCsv}
      />

      {importResult && (
        <div className="card stack" style={{ gap: "0.4rem" }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>
              Import complete: {importResult.created} created, {importResult.errors.length} error(s)
            </strong>
            <button className="btn" onClick={() => setImportResult(null)}>
              Dismiss
            </button>
          </div>
          {importResult.errors.length > 0 && (
            <ul style={{ margin: 0 }}>
              {importResult.errors.map((e, i) => (
                <li key={i} className="text-muted">
                  Row {e.row}: {e.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {showNewForm && metaLoaded && (components.length === 0 || categories.length === 0) && (
        <div className="card stack">
          <p style={{ margin: 0 }}>{strings.requirements.noComponentsOrCategories}</p>
          {canManageProject ? (
            <div className="stack">
              {components.length === 0 && (
                <div className="row">
                  <input
                    className="input"
                    placeholder={strings.admin.name}
                    value={newInlineComponentName}
                    onChange={(e) => setNewInlineComponentName(e.target.value)}
                  />
                  <input
                    className="input"
                    style={{ maxWidth: 100 }}
                    placeholder={strings.admin.prefix}
                    value={newInlineComponentPrefix}
                    onChange={(e) => setNewInlineComponentPrefix(e.target.value.toUpperCase())}
                  />
                  <button
                    className="btn btn-primary"
                    onClick={createInlineComponent}
                    disabled={!newInlineComponentName || !newInlineComponentPrefix}
                  >
                    <Plus size={14} /> {strings.admin.newComponent}
                  </button>
                </div>
              )}
              {categories.length === 0 && components.length > 0 && (
                <div className="row">
                  {components.length > 1 && (
                    <select className="input" style={{ maxWidth: 200 }} value={newComponentId} onChange={(e) => setNewComponentId(e.target.value)}>
                      {components.map((c) => (
                        <option key={c.id} value={c.id}>{c.name}</option>
                      ))}
                    </select>
                  )}
                  <input
                    className="input"
                    placeholder={strings.admin.name}
                    value={newInlineCategoryName}
                    onChange={(e) => setNewInlineCategoryName(e.target.value)}
                  />
                  <input
                    className="input"
                    style={{ maxWidth: 100 }}
                    placeholder={strings.admin.prefix}
                    value={newInlineCategoryPrefix}
                    onChange={(e) => setNewInlineCategoryPrefix(e.target.value.toUpperCase())}
                  />
                  <button
                    className="btn btn-primary"
                    onClick={createInlineCategory}
                    disabled={!newInlineCategoryName || !newInlineCategoryPrefix}
                  >
                    <Plus size={14} /> {strings.admin.newCategory}
                  </button>
                </div>
              )}
            </div>
          ) : (
            <Link to={`/projects/${projectId}/admin`} className="btn btn-primary" style={{ alignSelf: "flex-start" }}>
              {strings.requirements.configureComponentsFirst}
            </Link>
          )}
        </div>
      )}

      {showNewForm && metaLoaded && components.length > 0 && categories.length > 0 && (
        <div className="card stack">
          <input className="input" placeholder={strings.requirements.name} value={newName} onChange={(e) => setNewName(e.target.value)} />
          <textarea
            className="input"
            placeholder={strings.requirements.reasoning}
            value={newReasoning}
            onChange={(e) => setNewReasoning(e.target.value)}
            rows={2}
          />
          <textarea
            className="input"
            placeholder={strings.requirements.description}
            value={newDescription}
            onChange={(e) => setNewDescription(e.target.value)}
            rows={2}
          />
          <div className="row">
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.requirements.component}
              <select
                className="input"
                value={newComponentId}
                onChange={(e) => {
                  const componentId = e.target.value;
                  setNewComponentId(componentId);
                  // Category is nested under one component (the tree) — a
                  // category belonging to the previously-selected component
                  // is never valid once the component changes.
                  const firstOwnCategory = categories.find((c) => c.component_id === componentId);
                  setNewCategoryId(firstOwnCategory?.id ?? "");
                }}
              >
                {components.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.prefix})
                  </option>
                ))}
              </select>
            </label>
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.requirements.category}
              <select className="input" value={newCategoryId} onChange={(e) => setNewCategoryId(e.target.value)}>
                {categories.filter((c) => c.component_id === newComponentId).length === 0 && (
                  <option value="">{strings.requirements.noCategoriesForComponent}</option>
                )}
                {categories.filter((c) => c.component_id === newComponentId).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.prefix})
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="row">
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.requirements.targetVersion}
              <select className="input" value={newTargetStageId} onChange={(e) => setNewTargetStageId(e.target.value)}>
                {stages.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              {strings.requirements.level}
              <select className="input" value={newLevel} onChange={(e) => setNewLevel(e.target.value as RequirementLevel)}>
                <option value="requirement">{REQUIREMENT_LEVEL_LABEL.requirement}</option>
                <option value="recommended">{REQUIREMENT_LEVEL_LABEL.recommended}</option>
                <option value="optional">{REQUIREMENT_LEVEL_LABEL.optional}</option>
              </select>
            </label>
          </div>
          <CustomFieldsForm
            definitions={customFieldDefs}
            values={customFieldValues}
            onChange={(fieldId, value) => setCustomFieldValues((v) => ({ ...v, [fieldId]: value }))}
          />
          <button
            className="btn btn-primary"
            onClick={createRequirement}
            disabled={!newName || !newComponentId || !newCategoryId || !newTargetStageId}
          >
            {strings.common.create}
          </button>
        </div>
      )}

      <div className="side-grid">
        <div className="stack">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <input
              className="input"
              style={{ maxWidth: 320 }}
              placeholder={strings.requirements.search}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <ViewToggle mode={viewMode} onChange={setViewMode} />
          </div>

          {!requirements && <Spinner />}
          {requirements && requirements.length === 0 && <p className="text-muted">{strings.requirements.empty}</p>}
          {requirements && requirements.length > 0 && viewMode === "tiles" && (
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(min(280px, 100%), 1fr))" }}>
              {requirements.map((r) => (
                <div key={r.id} className="card stack" style={{ gap: "0.5rem" }}>
                  <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                    <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                      {r.unique_code}
                    </span>
                    <div className="row" style={{ gap: "0.25rem" }}>
                      <button className="btn" onClick={() => move(r.id, "up")} title={strings.common.up} aria-label={strings.common.up}>
                        <ArrowUp size={14} />
                      </button>
                      <button className="btn" onClick={() => move(r.id, "down")} title={strings.common.down} aria-label={strings.common.down}>
                        <ArrowDown size={14} />
                      </button>
                    </div>
                  </div>
                  <Link to={`/projects/${projectId}/requirements/${r.id}`} style={{ fontWeight: 600 }}>
                    {r.name}
                  </Link>
                  {r.reasoning && (
                    <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                      {r.reasoning.length > 140 ? `${r.reasoning.slice(0, 140)}…` : r.reasoning}
                    </p>
                  )}
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <div className="row" style={{ gap: "0.4rem" }}>
                      <FilterBadge active={statusFilter === r.status} onClick={() => toggleStatusFilter(r.status)}>
                        {REQUIREMENT_STATUS_LABEL[r.status]}
                      </FilterBadge>
                      {r.is_locked && <span className="badge">{strings.requirements.locked}</span>}
                    </div>
                    <div className="row" style={{ gap: "0.5rem" }}>{badges(r)}</div>
                  </div>
                  <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                    {componentName(r.component_id)} · {categoryName(r.category_id)}
                  </div>
                  <div className="text-muted" style={{ fontSize: "0.8rem" }}>
                    Target: {stageName(r.target_stage_id)} · Level: {REQUIREMENT_LEVEL_LABEL[r.level]}
                  </div>
                </div>
              ))}
            </div>
          )}
          {requirements && requirements.length > 0 && viewMode === "list" && (
            <div className="card" style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th style={{ width: "9%" }}>ID</th>
                    <th style={{ width: "38%" }}>Name</th>
                    <th>{strings.changeRequests.status}</th>
                    <th>Target · level</th>
                    <th>Component · category</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {requirements.map((r) => (
                    <tr key={r.id}>
                      <td className="text-muted">{r.unique_code}</td>
                      <td>
                        <Link to={`/projects/${projectId}/requirements/${r.id}`}>{r.name}</Link>
                      </td>
                      <td>
                        <div className="row" style={{ gap: "0.4rem" }}>
                          <FilterBadge active={statusFilter === r.status} onClick={() => toggleStatusFilter(r.status)}>
                            {REQUIREMENT_STATUS_LABEL[r.status]}
                          </FilterBadge>
                          {r.is_locked && <span className="badge">{strings.requirements.locked}</span>}
                          {badges(r)}
                        </div>
                      </td>
                      <td className="text-muted">
                        {stageName(r.target_stage_id)} · {REQUIREMENT_LEVEL_LABEL[r.level]}
                      </td>
                      <td className="text-muted">
                        {componentName(r.component_id)} · {categoryName(r.category_id)}
                      </td>
                      <td>
                        <div className="row" style={{ gap: "0.25rem" }}>
                          <button className="btn" onClick={() => move(r.id, "up")} title={strings.common.up} aria-label={strings.common.up}>
                            <ArrowUp size={14} />
                          </button>
                          <button className="btn" onClick={() => move(r.id, "down")} title={strings.common.down} aria-label={strings.common.down}>
                            <ArrowDown size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {requirements && (
            <LoadMoreButton
              loaded={requirements.length}
              total={total}
              onClick={() => loadRequirements(requirements.length, true)}
            />
          )}
        </div>

        <FilterPanel>
          <h2 style={{ margin: 0, fontSize: "1rem" }}>Filters</h2>
          <FilterField label="Status">
            <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as RequirementStatus | "")}>
              <option value="">All statuses</option>
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </FilterField>
          <FilterField label="Target version">
            <select className="input" value={targetStageFilter} onChange={(e) => setTargetStageFilter(e.target.value)}>
              <option value="">All versions</option>
              {stages.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </FilterField>
          <FilterField label="Category">
            <select className="input" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
              <option value="">All categories</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </FilterField>
          <FilterCheckbox label="Has comments" checked={hasCommentsOnly} onChange={setHasCommentsOnly} />
          <FilterCheckbox label="Only watched" checked={onlyWatched} onChange={setOnlyWatched} />
        </FilterPanel>
      </div>
    </div>
  );
}
