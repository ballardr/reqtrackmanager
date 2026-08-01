import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, fileUrl } from "../api/client";
import type { Comment, CustomFieldDefinition, FileAsset, Requirement, RequirementVersionEntry } from "../api/types";
import { CustomFieldsForm } from "../components/CustomFieldsForm";
import { Spinner } from "../components/Spinner";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Requirement detail view: direct editing while unlocked, a discussion
 * thread (C-R-01), and a change log that intentionally excludes discussion
 * comments (C-A-09 clarification).
 */
export function RequirementDetailPage() {
  const { projectId, requirementId } = useParams<{ projectId: string; requirementId: string }>();
  const navigate = useNavigate();
  const [requirement, setRequirement] = useState<Requirement | null>(null);
  const [history, setHistory] = useState<RequirementVersionEntry[]>([]);
  const [comments, setComments] = useState<Comment[]>([]);
  const [newComment, setNewComment] = useState("");
  const [form, setForm] = useState({ name: "", reasoning: "", clarification: "", changeNote: "" });
  const [saveError, setSaveError] = useState<string | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);
  const [customFieldDefs, setCustomFieldDefs] = useState<CustomFieldDefinition[]>([]);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});

  async function reload() {
    if (!projectId || !requirementId) return;
    const [req, hist, comm, fls, defs] = await Promise.all([
      api.get<Requirement>(`/api/v1/projects/${projectId}/requirements/${requirementId}`),
      api.get<RequirementVersionEntry[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/history`),
      api.get<Comment[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments`),
      api.get<FileAsset[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/files`),
      api.get<CustomFieldDefinition[]>(`/api/v1/projects/${projectId}/custom-fields?entity_kind=requirement`),
    ]);
    setRequirement(req);
    setHistory(hist);
    setComments(comm);
    setFiles(fls);
    setCustomFieldDefs(defs);
    setCustomFieldValues(req.custom_fields);
    setForm({ name: req.name, reasoning: req.reasoning, clarification: req.clarification, changeNote: "" });
  }

  async function uploadFile(file: File) {
    await api.postFile(`/api/v1/projects/${projectId}/requirements/${requirementId}/files`, file);
    reload();
  }

  async function removeFile(fileId: string) {
    await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}/files/${fileId}`);
    reload();
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, requirementId]);

  async function save() {
    if (!requirement) return;
    setSaveError(null);
    try {
      await api.put(`/api/v1/projects/${projectId}/requirements/${requirementId}`, {
        name: form.name,
        reasoning: form.reasoning,
        clarification: form.clarification,
        component_id: requirement.component_id,
        category_id: requirement.category_id,
        owner_id: requirement.owner_id,
        keywords: requirement.keywords,
        custom_fields: customFieldValues,
        change_note: form.changeNote,
      });
      reload();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function archive() {
    await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}`);
    navigate(`/projects/${projectId}/requirements`);
  }

  async function postComment() {
    if (!newComment.trim()) return;
    await api.post(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments`, { body: newComment });
    setNewComment("");
    reload();
  }

  if (!requirement) return <Spinner />;

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>
          {requirement.unique_code} — {requirement.name}
        </h1>
        <button className="btn btn-danger" onClick={archive}>
          {strings.requirements.archive}
        </button>
      </div>

      <div className="card stack">
        {requirement.is_locked && (
          <div className="badge" style={{ alignSelf: "flex-start" }}>
            {strings.requirements.locked} — use a change request to modify
          </div>
        )}
        <label className="stack" style={{ gap: "0.25rem" }}>
          Name
          <input
            className="input"
            value={form.name}
            disabled={requirement.is_locked}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          Reasoning
          <textarea
            className="input"
            rows={3}
            value={form.reasoning}
            disabled={requirement.is_locked}
            onChange={(e) => setForm((f) => ({ ...f, reasoning: e.target.value }))}
          />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          Clarification
          <textarea
            className="input"
            rows={2}
            value={form.clarification}
            disabled={requirement.is_locked}
            onChange={(e) => setForm((f) => ({ ...f, clarification: e.target.value }))}
          />
        </label>
        <CustomFieldsForm
          definitions={customFieldDefs}
          values={customFieldValues}
          disabled={requirement.is_locked}
          onChange={(fieldId, value) => setCustomFieldValues((v) => ({ ...v, [fieldId]: value }))}
        />
        {!requirement.is_locked && (
          <>
            <input
              className="input"
              placeholder={strings.requirements.changeNote}
              value={form.changeNote}
              onChange={(e) => setForm((f) => ({ ...f, changeNote: e.target.value }))}
            />
            {saveError && <div style={{ color: "var(--color-danger)" }}>{saveError}</div>}
            <button className="btn btn-primary" onClick={save} style={{ alignSelf: "flex-start" }}>
              {strings.requirements.save}
            </button>
          </>
        )}
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.history}</h2>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Status</th>
              <th>Change note</th>
              <th>When</th>
            </tr>
          </thead>
          <tbody>
            {history.map((h) => (
              <tr key={h.version_number}>
                <td>{h.version_number}</td>
                <td>{h.status}</td>
                <td>{h.change_note}</td>
                <td>{new Date(h.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.attachments}</h2>
        {files.map((f) => (
          <div key={f.id} className="row" style={{ justifyContent: "space-between" }}>
            <a href={fileUrl(f.id)} target="_blank" rel="noreferrer">
              {f.filename}
            </a>
            <button className="btn btn-danger" onClick={() => removeFile(f.id)}>
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        <input type="file" onChange={(e) => e.target.files?.[0] && uploadFile(e.target.files[0])} />
      </div>

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.discussion}</h2>
        {comments.map((c) => (
          <div key={c.id} className="card">
            <div className="text-muted" style={{ fontSize: "0.8rem" }}>
              {new Date(c.created_at).toLocaleString()}
            </div>
            <div>{c.body}</div>
          </div>
        ))}
        <div className="row">
          <input
            className="input"
            placeholder={strings.requirements.addComment}
            value={newComment}
            onChange={(e) => setNewComment(e.target.value)}
          />
          <button className="btn" onClick={postComment}>
            {strings.requirements.addComment}
          </button>
        </div>
      </div>
    </div>
  );
}
