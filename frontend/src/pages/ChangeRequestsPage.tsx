import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  ChangeRequest,
  ChangeRequestStatus,
  Component,
  Category,
  CustomFieldDefinition,
  ProjectStage,
  Requirement,
  RequirementLevel,
} from "../api/types";
import { CustomFieldsForm } from "../components/CustomFieldsForm";
import { FilterField, FilterPanel } from "../components/FilterPanel";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { Spinner } from "../components/Spinner";
import { useViewMode, ViewToggle } from "../components/ViewToggle";
import { useTerm, useTermPlural } from "../context/TerminologyContext";
import { t } from "../i18n/strings";

const strings = t();

const PAGE_SIZE = 30;

const CR_STATUS_OPTIONS: ChangeRequestStatus[] = [
  "draft", "submitted", "in_review", "approved", "rejected", "withdrawn",
];

/** Change request list and creation form (introduction, C-G-03), with
 * incremental "load more" pagination (U-P-06) for large CR sets. */
export function ChangeRequestsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [crs, setCrs] = useState<ChangeRequest[] | null>(null);
  const [total, setTotal] = useState(0);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [components, setComponents] = useState<Component[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [kind, setKind] = useState<"new_requirement" | "modify_requirement">("modify_requirement");
  const [requirementId, setRequirementId] = useState("");
  const [componentId, setComponentId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [proposedName, setProposedName] = useState("");
  const [proposedReasoning, setProposedReasoning] = useState("");
  const [reason, setReason] = useState("");
  const [proposedTargetStageId, setProposedTargetStageId] = useState("");
  const [proposedLevel, setProposedLevel] = useState<RequirementLevel>("requirement");
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [customFieldDefs, setCustomFieldDefs] = useState<CustomFieldDefinition[]>([]);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});
  const changeRequestTerm = useTerm("change_request");
  const changeRequestsTerm = useTermPlural("change_request");
  const [viewMode, setViewMode] = useViewMode("change-requests");
  const [statusFilter, setStatusFilter] = useState<ChangeRequestStatus | "">("");
  const [targetStageFilter, setTargetStageFilter] = useState("");

  function listParams(offset: number): URLSearchParams {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (statusFilter) params.set("cr_status", statusFilter);
    if (targetStageFilter) params.set("target_stage_id", targetStageFilter);
    return params;
  }

  async function loadChangeRequests(offset: number, append: boolean) {
    if (!projectId) return;
    const page = await api.getPage<ChangeRequest>(
      `/api/v1/projects/${projectId}/change-requests?${listParams(offset).toString()}`
    );
    setCrs((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
  }

  async function reload() {
    if (!projectId) return;
    const [reqs, comps, cats, defs, stgs] = await Promise.all([
      api.get<Requirement[]>(`/api/v1/projects/${projectId}/requirements`),
      api.get<Component[]>(`/api/v1/projects/${projectId}/components`),
      api.get<Category[]>(`/api/v1/projects/${projectId}/categories`),
      api.get<CustomFieldDefinition[]>(`/api/v1/projects/${projectId}/custom-fields?entity_kind=requirement`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      loadChangeRequests(0, false),
    ]);
    setRequirements(reqs);
    setComponents(comps);
    setCategories(cats);
    setCustomFieldDefs(defs);
    setStages(stgs);
    if (!requirementId && reqs[0]) setRequirementId(reqs[0].id);
    if (!componentId && comps[0]) setComponentId(comps[0].id);
    if (!categoryId && cats[0]) setCategoryId(cats[0].id);
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, statusFilter, targetStageFilter]);

  async function createCr() {
    await api.post(`/api/v1/projects/${projectId}/change-requests`, {
      kind,
      requirement_id: kind === "modify_requirement" ? requirementId : null,
      proposed_name: proposedName,
      proposed_reasoning: proposedReasoning,
      proposed_component_id: kind === "new_requirement" ? componentId : null,
      proposed_category_id: kind === "new_requirement" ? categoryId : null,
      proposed_target_stage_id: proposedTargetStageId || null,
      proposed_level: proposedLevel,
      reason,
      custom_fields: customFieldValues,
    });
    setProposedName("");
    setProposedReasoning("");
    setReason("");
    setProposedTargetStageId("");
    setProposedLevel("requirement");
    setCustomFieldValues({});
    setShowForm(false);
    reload();
  }

  function stageName(id: string | null) {
    return stages.find((s) => s.id === id)?.name ?? "—";
  }

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>{changeRequestsTerm}</h1>
        <button className="btn btn-primary" onClick={() => setShowForm((v) => !v)}>
          <Plus size={16} /> New {changeRequestTerm}
        </button>
      </div>

      {showForm && (
        <div className="card stack">
          <div className="row">
            <label>
              <input
                type="radio"
                checked={kind === "modify_requirement"}
                onChange={() => setKind("modify_requirement")}
              />{" "}
              {strings.changeRequests.kindModify}
            </label>
            <label>
              <input type="radio" checked={kind === "new_requirement"} onChange={() => setKind("new_requirement")} />{" "}
              {strings.changeRequests.kindNew}
            </label>
          </div>
          {kind === "modify_requirement" ? (
            <select className="input" value={requirementId} onChange={(e) => setRequirementId(e.target.value)}>
              {requirements.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.unique_code} — {r.name}
                </option>
              ))}
            </select>
          ) : (
            <div className="row">
              <select className="input" value={componentId} onChange={(e) => setComponentId(e.target.value)}>
                {components.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
              <select className="input" value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <input
            className="input"
            placeholder={strings.changeRequests.proposedName}
            value={proposedName}
            onChange={(e) => setProposedName(e.target.value)}
          />
          <textarea
            className="input"
            rows={2}
            placeholder={strings.changeRequests.proposedReasoning}
            value={proposedReasoning}
            onChange={(e) => setProposedReasoning(e.target.value)}
          />
          <textarea
            className="input"
            rows={2}
            placeholder={strings.changeRequests.reason}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="row">
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              Target version
              <select
                className="input"
                value={proposedTargetStageId}
                onChange={(e) => setProposedTargetStageId(e.target.value)}
              >
                <option value="">—</option>
                {stages.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              Level
              <select
                className="input"
                value={proposedLevel}
                onChange={(e) => setProposedLevel(e.target.value as RequirementLevel)}
              >
                <option value="requirement">Requirement</option>
                <option value="recommended">Recommended</option>
              </select>
            </label>
          </div>
          <CustomFieldsForm
            definitions={customFieldDefs}
            values={customFieldValues}
            onChange={(fieldId, value) => setCustomFieldValues((v) => ({ ...v, [fieldId]: value }))}
          />
          <button className="btn btn-primary" onClick={createCr} disabled={!proposedName || !reason}>
            {strings.common.create}
          </button>
        </div>
      )}

      <div className="grid" style={{ gridTemplateColumns: "1fr 240px", alignItems: "start", gap: "1rem" }}>
        <div className="stack">
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <ViewToggle mode={viewMode} onChange={setViewMode} />
          </div>

          {!crs && <Spinner />}
          {crs && viewMode === "list" && (
            <div className="card" style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>{strings.changeRequests.status}</th>
                    <th>Target</th>
                    <th>Level</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {crs.map((cr) => (
                    <tr key={cr.id}>
                      <td>
                        <Link to={`/projects/${projectId}/change-requests/${cr.id}`}>{cr.proposed_name}</Link>
                      </td>
                      <td>
                        <span className="badge">{cr.status}</span>
                      </td>
                      <td className="text-muted">{stageName(cr.proposed_target_stage_id)}</td>
                      <td className="text-muted">{cr.proposed_level}</td>
                      <td>{new Date(cr.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {crs && viewMode === "tiles" && (
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
              {crs.map((cr) => (
                <div key={cr.id} className="card stack" style={{ gap: "0.5rem" }}>
                  <Link to={`/projects/${projectId}/change-requests/${cr.id}`} style={{ fontWeight: 600 }}>
                    {cr.proposed_name}
                  </Link>
                  <div className="row" style={{ gap: "0.4rem" }}>
                    <span className="badge">{cr.status}</span>
                    <span className="badge">{stageName(cr.proposed_target_stage_id)}</span>
                    <span className="badge">{cr.proposed_level}</span>
                  </div>
                  <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                    {new Date(cr.created_at).toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          )}
          {crs && <LoadMoreButton loaded={crs.length} total={total} onClick={() => loadChangeRequests(crs.length, true)} />}
        </div>

        <FilterPanel>
          <h2 style={{ margin: 0, fontSize: "1rem" }}>Filters</h2>
          <FilterField label="Status">
            <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as ChangeRequestStatus | "")}>
              <option value="">All statuses</option>
              {CR_STATUS_OPTIONS.map((s) => (
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
        </FilterPanel>
      </div>
    </div>
  );
}
