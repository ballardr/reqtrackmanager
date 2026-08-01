import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { ChangeRequest, Component, Category, CustomFieldDefinition, Requirement } from "../api/types";
import { CustomFieldsForm } from "../components/CustomFieldsForm";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

/** Change request list and creation form (introduction, C-G-03). */
export function ChangeRequestsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [crs, setCrs] = useState<ChangeRequest[] | null>(null);
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
  const [customFieldDefs, setCustomFieldDefs] = useState<CustomFieldDefinition[]>([]);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});

  async function reload() {
    if (!projectId) return;
    const [list, reqs, comps, cats, defs] = await Promise.all([
      api.get<ChangeRequest[]>(`/api/v1/projects/${projectId}/change-requests`),
      api.get<Requirement[]>(`/api/v1/projects/${projectId}/requirements`),
      api.get<Component[]>(`/api/v1/projects/${projectId}/components`),
      api.get<Category[]>(`/api/v1/projects/${projectId}/categories`),
      api.get<CustomFieldDefinition[]>(`/api/v1/projects/${projectId}/custom-fields?entity_kind=requirement`),
    ]);
    setCrs(list);
    setRequirements(reqs);
    setComponents(comps);
    setCategories(cats);
    setCustomFieldDefs(defs);
    if (!requirementId && reqs[0]) setRequirementId(reqs[0].id);
    if (!componentId && comps[0]) setComponentId(comps[0].id);
    if (!categoryId && cats[0]) setCategoryId(cats[0].id);
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function createCr() {
    await api.post(`/api/v1/projects/${projectId}/change-requests`, {
      kind,
      requirement_id: kind === "modify_requirement" ? requirementId : null,
      proposed_name: proposedName,
      proposed_reasoning: proposedReasoning,
      proposed_component_id: kind === "new_requirement" ? componentId : null,
      proposed_category_id: kind === "new_requirement" ? categoryId : null,
      reason,
      custom_fields: customFieldValues,
    });
    setProposedName("");
    setProposedReasoning("");
    setReason("");
    setCustomFieldValues({});
    setShowForm(false);
    reload();
  }

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>{strings.changeRequests.title}</h1>
        <button className="btn btn-primary" onClick={() => setShowForm((v) => !v)}>
          <Plus size={16} /> {strings.changeRequests.newChangeRequest}
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
            placeholder="Proposed name"
            value={proposedName}
            onChange={(e) => setProposedName(e.target.value)}
          />
          <textarea
            className="input"
            rows={2}
            placeholder="Proposed reasoning"
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

      {!crs && <Spinner />}
      {crs && (
        <div className="card" style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>{strings.changeRequests.status}</th>
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
                  <td>{new Date(cr.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
