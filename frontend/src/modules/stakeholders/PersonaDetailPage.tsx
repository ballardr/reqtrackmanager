/**
 * Module: modules/stakeholders/PersonaDetailPage
 *
 * A single Persona's detail: fields, lifecycle, owner/champion, version
 * history, attachments, comments, and — on the project route — this project's
 * weight override. One scope-aware component serving three routes
 * (`module.ts`): a project persona and an org persona opened *from a
 * project* (both `/projects/:projectId/...`), and an org persona opened from
 * the org dashboard (`/orgs/:organizationId/...`).
 *
 * An org persona viewed inside a project is read-only here apart from the
 * weight override and comments (the project API can't mutate it); a link
 * leads to the org route where the owner role can edit it.
 *
 * Weight: the project route shows the *effective* weight with an
 * `OverridePill` naming the tier it came from ("Set on this project" /
 * "Inherited from parent project" / …) and a one-click "Use inherited value"
 * way back (docs/ux-style-guide.md principle 2 and "Pattern: scoring and
 * inherited settings"); the org route shows only the persona's own weight.
 *
 * Personas have no approval gate, so lifecycle is Activate / Retire /
 * Reactivate, each behind a tier-1 `ConfirmDialog` with an optional comment.
 * Every mutating control always renders regardless of role; the backend
 * enforces `persona_owner`/`org_persona_owner` and a 403 surfaces as a toast.
 * Owner and champion use `AssigneePicker`; assigning sends a partial update
 * carrying only that field.
 */
import { Pencil } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../../api/client";
import type { FileAsset, OrgUser, Project } from "../../api/types";
import { ArtefactCommentsSection } from "../../components/ArtefactCommentsSection";
import { AssigneePicker } from "../../components/AssigneePicker";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { FileAttachmentList } from "../../components/FileAttachmentList";
import { OverridePill } from "../../components/OverridePill";
import { Spinner } from "../../components/Spinner";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgPersonaApi, orgPersonaTypeApi, projectPersonaApi } from "./api";
import { PersonaFormModal } from "./PersonaFormModal";
import type { Persona, PersonaComment, PersonaFieldValues, PersonaVersion } from "./types";
import { PERSONA_SCOPE_LABEL, PERSONA_STATUS_LABEL, PERSONA_STATUS_TONE, PERSONA_WEIGHT_SOURCE_LABEL } from "./types";

type TransitionAction = "activate" | "retire";

const TRANSITION_COPY: Record<TransitionAction, { title: string; body: string; confirmLabel: string; done: string }> = {
  activate: {
    title: "Activate this Persona?",
    body: "An Active persona is offered as a target when scoring. A comment is optional.",
    confirmLabel: "Activate",
    done: "Persona activated.",
  },
  retire: {
    title: "Retire this Persona?",
    body: "A Retired persona is no longer offered when scoring, but keeps its history and can be reactivated. A comment is optional.",
    confirmLabel: "Retire",
    done: "Persona retired.",
  },
};

export function PersonaDetailPage() {
  const { projectId, organizationId, personaId } = useParams<{
    projectId?: string;
    organizationId?: string;
    personaId: string;
  }>();
  const { user } = useAuth();
  const { showToast } = useToast();
  const scopedApi = projectId ? projectPersonaApi : orgPersonaApi;
  const scopeId = projectId ?? organizationId;
  const backLink = projectId ? `/projects/${projectId}/modules/stakeholders/personas` : "/org-overview";
  const backLabel = projectId ? "← Personas" : "← Organisation overview";

  const [persona, setPersona] = useState<Persona | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [versions, setVersions] = useState<PersonaVersion[] | null>(null);
  const [comments, setComments] = useState<PersonaComment[] | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [projectOrgId, setProjectOrgId] = useState<string | undefined>(undefined);
  const [typeOptions, setTypeOptions] = useState<{ value: string; label: string }[]>([]);

  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [transitionAction, setTransitionAction] = useState<TransitionAction | null>(null);
  const [transitionComment, setTransitionComment] = useState("");
  const [archiveConfirm, setArchiveConfirm] = useState(false);
  const [weightInput, setWeightInput] = useState("");

  // An org persona opened inside a project can't be mutated through the project API.
  const readOnlyInProject = !!projectId && persona?.scope === "organization";

  useEffect(() => {
    if (!scopeId || !personaId) return;
    scopedApi.get(scopeId, personaId).then(setPersona).catch((err) => {
      setLoadError(toErrorMessage(err, "This Persona could not be found, or you don't have access to it."));
    });
    scopedApi.listVersions(scopeId, personaId).then(setVersions).catch(() => setVersions([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeId, personaId]);

  // The org id the user pickers need: given directly on the org route, else
  // resolved once from the owning project.
  const ownerOrgId = organizationId ?? projectOrgId;
  useEffect(() => {
    if (organizationId || !projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then((p) => setProjectOrgId(p.organization_id));
  }, [projectId, organizationId]);

  useEffect(() => {
    if (!ownerOrgId) return;
    void api.get<OrgUser[]>(`/api/v1/orgs/${ownerOrgId}/users`).then(setOrgUsers).catch(() => setOrgUsers([]));
  }, [ownerOrgId]);

  useEffect(() => {
    if (!scopeId) return;
    const load = projectId
      ? projectPersonaApi.listTypes(scopeId).then((list) => list.filter((t) => t.is_enabled).map((t) => ({ value: t.id, label: t.name })))
      : orgPersonaTypeApi.list(scopeId).then((list) => list.filter((t) => t.is_active).map((t) => ({ value: t.id, label: t.name })));
    load.then(setTypeOptions).catch(() => setTypeOptions([]));
  }, [scopeId, projectId]);

  useEffect(() => {
    if (!scopeId || !personaId) return;
    let active = true;
    Promise.all([scopedApi.listComments(scopeId, personaId), scopedApi.listFiles(scopeId, personaId)])
      .then(([c, f]) => {
        if (!active) return;
        setComments(c);
        setFiles(f);
      })
      .catch((err) => showToast(toErrorMessage(err, "Could not load this Persona's comments/files."), "error"));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeId, personaId]);

  async function run(action: () => Promise<Persona>, successMessage: string, errorMessage = "Could not update this Persona.") {
    try {
      const updated = await action();
      showToast(successMessage);
      setPersona(updated);
      if (scopeId && personaId) void scopedApi.listVersions(scopeId, personaId).then(setVersions).catch(() => undefined);
    } catch (err) {
      showToast(toErrorMessage(err, errorMessage), "error");
    }
  }

  async function saveEdit(values: PersonaFieldValues) {
    if (!scopeId || !persona) return;
    setFormError(null);
    try {
      const updated = await scopedApi.update(scopeId, persona.id, values);
      showToast("Persona updated.");
      setEditing(false);
      setPersona(updated);
      void scopedApi.listVersions(scopeId, persona.id).then(setVersions).catch(() => undefined);
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not update this Persona."));
    }
  }

  if (!scopeId || !personaId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (persona === null) return <Spinner />;

  const weightSource = persona.weight_source ?? "none";
  const overridden = persona.weight_override !== null;
  const weightInputNumber = Number(weightInput);
  const weightInputValid = weightInput.trim() !== "" && Number.isFinite(weightInputNumber) && weightInputNumber > 0;

  return (
    <div className="container stack">
      <Link to={backLink}>{backLabel}</Link>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ margin: 0 }}>{persona.name}</h1>
        <span className="row" style={{ gap: "0.5rem" }}>
          <span className="badge">{PERSONA_SCOPE_LABEL[persona.scope]}</span>
          <span className={`badge badge--${PERSONA_STATUS_TONE[persona.status]}`}>{PERSONA_STATUS_LABEL[persona.status]}</span>
        </span>
      </div>

      <div className="stack">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <p className="text-muted" style={{ margin: 0 }}>
            {[persona.persona_type_name, persona.role_title].filter(Boolean).join(" · ") || "No type or role set"} · v{persona.version_number}
            {persona.is_archived && " · Archived"}
          </p>
          {!readOnlyInProject && (
            <button className="btn" title="Edit" aria-label="Edit" onClick={() => setEditing(true)}>
              <Pencil size={14} />
            </button>
          )}
        </div>

        {readOnlyInProject && (
          <p className="text-muted" style={{ margin: 0 }}>
            This is an organisation-wide Persona shared by every project. Edit it from the{" "}
            <Link to={`/orgs/${persona.organization_id}/modules/stakeholders/personas/${persona.id}`}>organisation view</Link>;
            you can still set this project's weight below.
          </p>
        )}

        {persona.description && <Field label="Description" value={persona.description} />}
        {persona.goals && <Field label="Goals" value={persona.goals} />}
        {persona.needs && <Field label="Needs" value={persona.needs} />}
        {persona.behaviours && <Field label="Behaviours" value={persona.behaviours} />}
        {persona.context_environment && <Field label="Context / environment" value={persona.context_environment} />}
        {persona.skills_proficiency && <Field label="Skills / proficiency" value={persona.skills_proficiency} />}
        {persona.frequency_of_use && <Field label="Frequency of use" value={persona.frequency_of_use} />}
        {persona.constraints && <Field label="Constraints" value={persona.constraints} />}

        <div className="stack" style={{ gap: "0.35rem" }}>
          <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>Importance weight</span>
          {projectId ? (
            <>
              <div className="row" style={{ gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
                <span data-testid="effective-weight">
                  {persona.effective_weight === null ? "Not weighted" : persona.effective_weight}
                </span>
                <OverridePill
                  custom={overridden}
                  defaultLabel={PERSONA_WEIGHT_SOURCE_LABEL[weightSource]}
                  resetLabel="Use inherited value"
                  onReset={() =>
                    run(() => projectPersonaApi.clearWeightOverride(projectId, persona.id), "Weight override removed.", "Could not remove the weight override.")
                  }
                />
              </div>
              <div className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
                <input
                  className="input"
                  type="number"
                  min="0"
                  step="any"
                  style={{ maxWidth: "10rem" }}
                  value={weightInput}
                  onChange={(e) => setWeightInput(e.target.value)}
                  aria-label="Project weight override"
                  placeholder="Override for this project"
                />
                <button
                  className="btn"
                  disabled={!weightInputValid}
                  onClick={async () => {
                    await run(() => projectPersonaApi.setWeightOverride(projectId, persona.id, weightInputNumber), "Weight override saved.", "Could not save the weight override.");
                    setWeightInput("");
                  }}
                >
                  Set override
                </button>
              </div>
              <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                The persona's own weight is {persona.weight === null ? "not set" : persona.weight}. An override applies to this project and any child project without its own.
              </span>
            </>
          ) : (
            <span>{persona.weight === null ? "Not weighted" : persona.weight}</span>
          )}
        </div>

        <div className="stack" style={{ gap: "0.25rem" }}>
          <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>Owner</span>
          {readOnlyInProject ? (
            <span>{orgUsers.find((u) => u.user_id === persona.owner_id)?.display_name ?? "Unassigned"}</span>
          ) : (
            <AssigneePicker
              orgUsers={orgUsers}
              organizationId={ownerOrgId}
              assigneeId={persona.owner_id}
              onChange={(ownerId) =>
                run(() => scopedApi.update(scopeId, persona.id, { owner_id: ownerId || null }), "Owner updated.", "Could not update this Persona's owner.")
              }
              ariaLabel="Persona owner"
            />
          )}
        </div>

        <div className="stack" style={{ gap: "0.25rem" }}>
          <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>Champion (keeps this persona accurate)</span>
          {readOnlyInProject ? (
            <span>{orgUsers.find((u) => u.user_id === persona.champion_id)?.display_name ?? "Unassigned"}</span>
          ) : (
            <AssigneePicker
              orgUsers={orgUsers}
              organizationId={ownerOrgId}
              assigneeId={persona.champion_id}
              onChange={(championId) =>
                run(() => scopedApi.update(scopeId, persona.id, { champion_id: championId || null }), "Champion updated.", "Could not update this Persona's champion.")
              }
              ariaLabel="Persona champion"
            />
          )}
        </div>

        {!readOnlyInProject && (
          <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
            {persona.status !== "active" && (
              <button className="btn btn-primary" onClick={() => setTransitionAction("activate")}>
                {persona.status === "retired" ? "Reactivate" : "Activate"}
              </button>
            )}
            {persona.status !== "retired" && (
              <button className="btn btn-danger" onClick={() => setTransitionAction("retire")}>Retire</button>
            )}
            <button className="btn" onClick={() => setArchiveConfirm(true)}>
              {persona.is_archived ? "Unarchive" : "Archive"}
            </button>
          </div>
        )}

        {versions && versions.length > 1 && (
          <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
            <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Version history</h3>
            <table className="table">
              <thead>
                <tr><th>Version</th><th>Status</th><th>Weight</th><th>Changed</th><th>Change note</th></tr>
              </thead>
              <tbody>
                {[...versions].reverse().map((v) => (
                  <tr key={v.id}>
                    <td>{v.version_number}</td>
                    <td>{PERSONA_STATUS_LABEL[v.status]}</td>
                    <td>{v.weight ?? "—"}</td>
                    <td>{new Date(v.valid_from).toLocaleString()}</td>
                    <td>{v.change_note || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
          <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Attachments</h3>
          <FileAttachmentList
            files={files}
            disabled={readOnlyInProject}
            emptyHint={readOnlyInProject ? "Attachments to an organisation Persona are managed from the organisation view." : undefined}
            onUpload={async (file) => {
              const asset = await scopedApi.uploadFile(scopeId, persona.id, file);
              setFiles((prev) => [...prev, asset]);
            }}
            onRemove={async (fileId) => {
              await scopedApi.unlinkFile(scopeId, persona.id, fileId);
              setFiles((prev) => prev.filter((f) => f.id !== fileId));
            }}
          />
        </div>

        <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
          <ArtefactCommentsSection
            comments={comments ?? []}
            currentUserId={user?.id}
            onPost={async (body) => {
              const comment = await scopedApi.addComment(scopeId, persona.id, body);
              setComments((prev) => [...(prev ?? []), comment]);
              return comment;
            }}
            onEdit={async (commentId, body) => {
              const updated = await scopedApi.editComment(scopeId, persona.id, commentId, body);
              setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? updated : c)));
            }}
            onUploadAttachment={async (commentId, file) => {
              const asset = await scopedApi.uploadCommentAttachment(scopeId, persona.id, commentId, file);
              setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: [...c.attachments, asset] } : c)));
            }}
            onRemoveAttachment={async (commentId, fileId) => {
              await scopedApi.removeCommentAttachment(scopeId, persona.id, commentId, fileId);
              setComments((prev) => (prev ?? []).map((c) => (c.id === commentId ? { ...c, attachments: c.attachments.filter((a) => a.id !== fileId) } : c)));
            }}
          />
        </div>
      </div>

      {editing && (
        <PersonaFormModal
          initial={persona}
          scopeLabel={projectId ? "project" : "organisation"}
          typeOptions={typeOptions}
          error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }}
          onSave={saveEdit}
        />
      )}

      {transitionAction && (
        <ConfirmDialog
          title={TRANSITION_COPY[transitionAction].title}
          message={
            <span className="stack" style={{ gap: "0.5rem" }}>
              <span>{TRANSITION_COPY[transitionAction].body}</span>
              <label className="stack" style={{ gap: "0.25rem" }}>
                Comment
                <textarea
                  className="input" rows={2} aria-label="Transition comment"
                  value={transitionComment} onChange={(e) => setTransitionComment(e.target.value)}
                />
              </label>
            </span>
          }
          confirmLabel={TRANSITION_COPY[transitionAction].confirmLabel}
          onConfirm={async () => {
            const action = transitionAction;
            const comment = transitionComment;
            setTransitionAction(null);
            setTransitionComment("");
            await run(() => scopedApi[action](scopeId, persona.id, comment), TRANSITION_COPY[action].done);
          }}
          onCancel={() => { setTransitionAction(null); setTransitionComment(""); }}
        />
      )}

      {archiveConfirm && (
        <ConfirmDialog
          title={persona.is_archived ? "Unarchive this Persona?" : "Archive this Persona?"}
          message={
            persona.is_archived
              ? "This Persona will count as active again."
              : "This Persona will no longer appear in the active list or be offered when scoring. Nothing is deleted."
          }
          confirmLabel={persona.is_archived ? "Unarchive" : "Archive"}
          onConfirm={async () => {
            setArchiveConfirm(false);
            await run(
              () => (persona.is_archived ? scopedApi.unarchive(scopeId, persona.id) : scopedApi.archive(scopeId, persona.id)),
              persona.is_archived ? "Persona unarchived." : "Persona archived.",
            );
          }}
          onCancel={() => setArchiveConfirm(false)}
        />
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="stack" style={{ gap: "0.15rem" }}>
      <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>{label}</span>
      <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{value}</p>
    </div>
  );
}
