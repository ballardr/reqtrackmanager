import { ArrowDown, ArrowUp, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Category, Component, CustomFieldDefinition, Requirement } from "../api/types";
import { CustomFieldsForm } from "../components/CustomFieldsForm";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Requirement browser (C-G-04: sorted by component/category), with search
 * by name/ID (U-E-01) and scoping-stage-only reordering (C-E-03).
 */
export function RequirementsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [requirements, setRequirements] = useState<Requirement[] | null>(null);
  const [components, setComponents] = useState<Component[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [search, setSearch] = useState("");
  const [showNewForm, setShowNewForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newReasoning, setNewReasoning] = useState("");
  const [newComponentId, setNewComponentId] = useState("");
  const [newCategoryId, setNewCategoryId] = useState("");
  const [customFieldDefs, setCustomFieldDefs] = useState<CustomFieldDefinition[]>([]);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});

  async function reload() {
    if (!projectId) return;
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    const [reqs, comps, cats, defs] = await Promise.all([
      api.get<Requirement[]>(`/api/v1/projects/${projectId}/requirements?${params.toString()}`),
      api.get<Component[]>(`/api/v1/projects/${projectId}/components`),
      api.get<Category[]>(`/api/v1/projects/${projectId}/categories`),
      api.get<CustomFieldDefinition[]>(`/api/v1/projects/${projectId}/custom-fields?entity_kind=requirement`),
    ]);
    setRequirements(reqs);
    setComponents(comps);
    setCategories(cats);
    setCustomFieldDefs(defs);
    if (!newComponentId && comps[0]) setNewComponentId(comps[0].id);
    if (!newCategoryId && cats[0]) setNewCategoryId(cats[0].id);
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, search]);

  async function createRequirement() {
    if (!projectId || !newComponentId || !newCategoryId) return;
    await api.post(`/api/v1/projects/${projectId}/requirements`, {
      name: newName,
      reasoning: newReasoning,
      component_id: newComponentId,
      category_id: newCategoryId,
      keywords: [],
      custom_fields: customFieldValues,
    });
    setNewName("");
    setNewReasoning("");
    setCustomFieldValues({});
    setShowNewForm(false);
    reload();
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

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>{strings.requirements.title}</h1>
        <button className="btn btn-primary" onClick={() => setShowNewForm((v) => !v)}>
          <Plus size={16} /> {strings.requirements.newRequirement}
        </button>
      </div>

      {showNewForm && (
        <div className="card stack">
          <input className="input" placeholder="Name" value={newName} onChange={(e) => setNewName(e.target.value)} />
          <textarea
            className="input"
            placeholder={strings.requirements.status}
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

      <input
        className="input"
        style={{ maxWidth: 320 }}
        placeholder={strings.requirements.search}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {!requirements && <Spinner />}
      {requirements && (
        <div className="card" style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>{strings.requirements.component}</th>
                <th>{strings.requirements.category}</th>
                <th>{strings.requirements.status}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {requirements.map((r) => (
                <tr key={r.id}>
                  <td>{r.unique_code}</td>
                  <td>
                    <Link to={`/projects/${projectId}/requirements/${r.id}`}>{r.name}</Link>
                    {r.is_locked && <span className="badge" style={{ marginLeft: 6 }}>{strings.requirements.locked}</span>}
                  </td>
                  <td>{componentName(r.component_id)}</td>
                  <td>{categoryName(r.category_id)}</td>
                  <td>{r.status}</td>
                  <td className="row">
                    <button className="btn" onClick={() => move(r.id, "up")} title={strings.common.up}>
                      <ArrowUp size={14} />
                    </button>
                    <button className="btn" onClick={() => move(r.id, "down")} title={strings.common.down}>
                      <ArrowDown size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
