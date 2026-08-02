import { ArrowDown, ArrowUp, GitPullRequest, MessageSquare, Plus, TriangleAlert, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  Category,
  Component,
  CustomFieldDefinition,
  ProjectStage,
  Requirement,
  RequirementImportResult,
  RequirementLevel,
  RequirementStatus,
} from "../api/types";
import { CustomFieldsForm } from "../components/CustomFieldsForm";
import { FilterCheckbox, FilterField, FilterPanel } from "../components/FilterPanel";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { Spinner } from "../components/Spinner";
import { useViewMode, ViewToggle } from "../components/ViewToggle";
import { useTerm, useTermPlural } from "../context/TerminologyContext";
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
  const [requirements, setRequirements] = useState<Requirement[] | null>(null);
  const [total, setTotal] = useState(0);
  const [components, setComponents] = useState<Component[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<RequirementStatus | "">("");
  const [targetStageFilter, setTargetStageFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [hasCommentsOnly, setHasCommentsOnly] = useState(false);
  const [onlyWatched, setOnlyWatched] = useState(false);
  const [showNewForm, setShowNewForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newReasoning, setNewReasoning] = useState("");
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
    if (!newComponentId && comps[0]) setNewComponentId(comps[0].id);
    if (!newCategoryId && cats[0]) setNewCategoryId(cats[0].id);
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, search, statusFilter, targetStageFilter, categoryFilter, hasCommentsOnly, onlyWatched]);

  async function createRequirement() {
    if (!projectId || !newComponentId || !newCategoryId) return;
    await api.post(`/api/v1/projects/${projectId}/requirements`, {
      name: newName,
      reasoning: newReasoning,
      component_id: newComponentId,
      category_id: newCategoryId,
      target_stage_id: newTargetStageId || null,
      level: newLevel,
      keywords: [],
      custom_fields: customFieldValues,
    });
    setNewName("");
    setNewReasoning("");
    setNewTargetStageId("");
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
        <div className="row">
          <label className="btn" style={{ cursor: importing ? "wait" : "pointer" }}>
            <Upload size={16} /> {importing ? "Importing…" : "Import CSV"}
            <input
              type="file"
              accept=".csv,text/csv"
              style={{ display: "none" }}
              disabled={importing}
              onChange={(e) => e.target.files?.[0] && importCsv(e.target.files[0])}
            />
          </label>
          <button className="btn btn-primary" onClick={() => setShowNewForm((v) => !v)}>
            <Plus size={16} /> New {requirementTerm}
          </button>
        </div>
      </div>

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

      {showNewForm && (
        <div className="card stack">
          <input className="input" placeholder={strings.requirements.name} value={newName} onChange={(e) => setNewName(e.target.value)} />
          <textarea
            className="input"
            placeholder={strings.requirements.reasoning}
            value={newReasoning}
            onChange={(e) => setNewReasoning(e.target.value)}
            rows={2}
          />
          <div className="row">
            <select className="input" value={newComponentId} onChange={(e) => setNewComponentId(e.target.value)}>
              {components.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.prefix})
                </option>
              ))}
            </select>
            <select className="input" value={newCategoryId} onChange={(e) => setNewCategoryId(e.target.value)}>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.prefix})
                </option>
              ))}
            </select>
          </div>
          <div className="row">
            <select className="input" value={newTargetStageId} onChange={(e) => setNewTargetStageId(e.target.value)}>
              <option value="">Target version —</option>
              {stages.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            <select className="input" value={newLevel} onChange={(e) => setNewLevel(e.target.value as RequirementLevel)}>
              <option value="requirement">Requirement</option>
              <option value="recommended">Recommended</option>
            </select>
          </div>
          <CustomFieldsForm
            definitions={customFieldDefs}
            values={customFieldValues}
            onChange={(fieldId, value) => setCustomFieldValues((v) => ({ ...v, [fieldId]: value }))}
          />
          <button className="btn btn-primary" onClick={createRequirement} disabled={!newName}>
            {strings.common.create}
          </button>
        </div>
      )}

      <div className="grid" style={{ gridTemplateColumns: "1fr 240px", alignItems: "start", gap: "1rem" }}>
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
          {requirements && viewMode === "tiles" && (
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
              {requirements.map((r) => (
                <div key={r.id} className="card stack" style={{ gap: "0.5rem" }}>
                  <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                    <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                      {r.unique_code}
                    </span>
                    <div className="row" style={{ gap: "0.25rem" }}>
                      <button className="btn" onClick={() => move(r.id, "up")} title={strings.common.up}>
                        <ArrowUp size={14} />
                      </button>
                      <button className="btn" onClick={() => move(r.id, "down")} title={strings.common.down}>
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
                      <span className="badge">{r.status}</span>
                      {r.is_locked && <span className="badge">{strings.requirements.locked}</span>}
                    </div>
                    <div className="row" style={{ gap: "0.5rem" }}>{badges(r)}</div>
                  </div>
                  <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                    {componentName(r.component_id)} · {categoryName(r.category_id)}
                  </div>
                  <div className="text-muted" style={{ fontSize: "0.8rem" }}>
                    Target: {stageName(r.target_stage_id)} · Level: {r.level}
                  </div>
                </div>
              ))}
            </div>
          )}
          {requirements && viewMode === "list" && (
            <div className="card" style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Name</th>
                    <th>{strings.changeRequests.status}</th>
                    <th>Target · Level</th>
                    <th>Component · Category</th>
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
                          <span className="badge">{r.status}</span>
                          {r.is_locked && <span className="badge">{strings.requirements.locked}</span>}
                          {badges(r)}
                        </div>
                      </td>
                      <td className="text-muted">
                        {stageName(r.target_stage_id)} · {r.level}
                      </td>
                      <td className="text-muted">
                        {componentName(r.component_id)} · {categoryName(r.category_id)}
                      </td>
                      <td>
                        <div className="row" style={{ gap: "0.25rem" }}>
                          <button className="btn" onClick={() => move(r.id, "up")} title={strings.common.up}>
                            <ArrowUp size={14} />
                          </button>
                          <button className="btn" onClick={() => move(r.id, "down")} title={strings.common.down}>
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
