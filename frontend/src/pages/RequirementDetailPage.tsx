import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, fileUrl } from "../api/client";
import type {
  ChangeEntry,
  Comment,
  CustomFieldDefinition,
  FileAsset,
  ProjectStage,
  Requirement,
  RequirementLevel,
  RequirementVersionEntry,
} from "../api/types";
import { ActivityPanel } from "../components/ActivityPanel";
import { CommentThread } from "../components/CommentThread";
import { CustomFieldsForm } from "../components/CustomFieldsForm";
import { Spinner } from "../components/Spinner";
import { SubscribeButton } from "../components/SubscribeButton";
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
  const [form, setForm] = useState({
    name: "",
    reasoning: "",
    clarification: "",
    changeNote: "",
    targetStageId: "",
    level: "requirement" as RequirementLevel,
  });
  const [saveError, setSaveError] = useState<string | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);
  const [customFieldDefs, setCustomFieldDefs] = useState<CustomFieldDefinition[]>([]);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [activity, setActivity] = useState<ChangeEntry[]>([]);

  async function reload() {
    if (!projectId || !requirementId) return;
    const [req, hist, comm, fls, defs, stgs, act] = await Promise.all([
      api.get<Requirement>(`/api/v1/projects/${projectId}/requirements/${requirementId}`),
      api.get<RequirementVersionEntry[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/history`),
      api.get<Comment[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments`),
      api.get<FileAsset[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/files`),
      api.get<CustomFieldDefinition[]>(`/api/v1/projects/${projectId}/custom-fields?entity_kind=requirement`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      api.get<ChangeEntry[]>(`/api/v1/projects/${projectId}/requirements/${requirementId}/activity`),
    ]);
    setRequirement(req);
    setHistory(hist);
    setComments(comm);
    setFiles(fls);
    setCustomFieldDefs(defs);
    setCustomFieldValues(req.custom_fields);
    setStages(stgs);
    setActivity(act);
    setForm({
      name: req.name,
      reasoning: req.reasoning,
      clarification: req.clarification,
      changeNote: "",
      targetStageId: req.target_stage_id ?? "",
      level: req.level,
    });
  }

  function stageName(id: string | null) {
    return stages.find((s) => s.id === id)?.name ?? "—";
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
        target_stage_id: form.targetStageId || null,
        level: form.level,
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

  async function toggleSubscription() {
    if (!requirement) return;
    if (requirement.is_subscribed) {
      await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}/subscription`);
    } else {
      await api.put(`/api/v1/projects/${projectId}/requirements/${requirementId}/subscription`);
    }
    reload();
  }

  async function postComment(body: string) {
    await api.post(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments`, { body });
    reload();
  }

  async function toggleReaction(commentId: string, reacted: boolean) {
    if (reacted) {
      await api.delete(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments/${commentId}/reaction`);
    } else {
      await api.put(`/api/v1/projects/${projectId}/requirements/${requirementId}/comments/${commentId}/reaction`);
    }
    reload();
  }

  if (!requirement) return <Spinner />;

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>
          {requirement.unique_code} — {requirement.name}
        </h1>
        <div className="row">
          <SubscribeButton subscribed={requirement.is_subscribed} onToggle={toggleSubscription} />
          <button className="btn btn-danger" onClick={archive}>
            {strings.requirements.archive}
          </button>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1fr 240px", alignItems: "start", gap: "1rem" }}>
      <div className="stack">
      {requirement.is_locked ? (
        <div className="card stack">
          <div className="badge" style={{ alignSelf: "flex-start" }}>
            {strings.requirements.locked} — {strings.requirements.lockedNotice}
          </div>
          <div>
            <div className="text-muted">{strings.requirements.description}</div>
            <p style={{ marginTop: "0.25rem" }}>{requirement.reasoning}</p>
          </div>
          {requirement.clarification && (
            <div>
              <div className="text-muted">{strings.requirements.clarification}</div>
              <p style={{ marginTop: "0.25rem" }}>{requirement.clarification}</p>
            </div>
          )}
          <div className="row">
            <span className="badge">{strings.requirements.status}: {requirement.status}</span>
            <span className="badge">Target: {stageName(requirement.target_stage_id)}</span>
            <span className="badge">Level: {requirement.level}</span>
            {requirement.keywords.map((k) => (
              <span key={k} className="badge">
                {k}
              </span>
            ))}
          </div>
          <CustomFieldsForm definitions={customFieldDefs} values={customFieldValues} disabled onChange={() => {}} />
        </div>
      ) : (
        <div className="card stack">
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.requirements.name}
            <input className="input" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          </label>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.requirements.reasoning}
            <textarea
              className="input"
              rows={3}
              value={form.reasoning}
              onChange={(e) => setForm((f) => ({ ...f, reasoning: e.target.value }))}
            />
          </label>
          <label className="stack" style={{ gap: "0.25rem" }}>
            {strings.requirements.clarification}
            <textarea
              className="input"
              rows={2}
              value={form.clarification}
              onChange={(e) => setForm((f) => ({ ...f, clarification: e.target.value }))}
            />
          </label>
          <div className="row">
            <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
              Target version
              <select
                className="input"
                value={form.targetStageId}
                onChange={(e) => setForm((f) => ({ ...f, targetStageId: e.target.value }))}
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
                value={form.level}
                onChange={(e) => setForm((f) => ({ ...f, level: e.target.value as RequirementLevel }))}
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
        </div>
      )}

      <div className="card stack">
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{strings.requirements.history}</h2>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>{strings.requirements.status}</th>
              <th>{strings.requirements.changeNote}</th>
              <th>{strings.requirements.when}</th>
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
        <CommentThread comments={comments} onPost={postComment} onToggleReaction={toggleReaction} />
      </div>
      </div>

      <ActivityPanel entries={activity} />
      </div>
    </div>
  );
}
