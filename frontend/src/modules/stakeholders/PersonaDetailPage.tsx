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
 * Reactivate, each behind a tier-1 `ConfirmDialog` with an optional comment
 * (`RecordLifecycleControls`). Every mutating control always renders
 * regardless of role; the backend enforces `persona_owner`/
 * `org_persona_owner` and a 403 surfaces as a toast. Owner and champion use
 * `RecordPersonField`; assigning sends a partial update carrying only that
 * field. Attachments and comments are `RecordDiscussion`, version history is
 * `VersionHistoryTable`, and the Stakeholders that represent this persona are
 * `RepresentedByPanel`.
 */
import { Pencil } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../../api/client";
import type { OrgUser, Project } from "../../api/types";
import { OverridePill } from "../../components/OverridePill";
import { Spinner } from "../../components/Spinner";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgPersonaApi, orgPersonaTypeApi, projectNeedApi, projectPersonaApi } from "./api";
import { HeldNeedsPanel } from "./HeldNeedsPanel";
import { PersonaFormModal } from "./PersonaFormModal";
import { RecordField, RecordFieldGroup, RecordPersonField, VersionHistoryTable } from "./RecordDetailParts";
import { RecordDiscussion } from "./RecordDiscussion";
import { RecordLifecycleControls, type LifecycleAction } from "./RecordLifecycleControls";
import { RelationshipsPanel } from "./RelationshipsPanel";
import { RepresentationPanel } from "./RepresentationPanel";
import type { Persona, PersonaFieldValues, PersonaVersion } from "./types";
import { PERSONA_SCOPE_LABEL, PERSONA_STATUS_LABEL, PERSONA_STATUS_TONE, PERSONA_WEIGHT_SOURCE_LABEL } from "./types";

const TRANSITION_DONE: Record<LifecycleAction, string> = {
  activate: "Persona activated.",
  retire: "Persona retired.",
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
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [projectOrgId, setProjectOrgId] = useState<string | undefined>(undefined);
  const [typeOptions, setTypeOptions] = useState<{ value: string; label: string }[]>([]);

  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
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

        {persona.description && <RecordField label="Description" value={persona.description} />}
        {persona.goals && <RecordField label="Goals" value={persona.goals} />}
        {persona.needs && <RecordField label="Needs" value={persona.needs} />}
        {persona.behaviours && <RecordField label="Behaviours" value={persona.behaviours} />}
        {persona.context_environment && <RecordField label="Context / environment" value={persona.context_environment} />}
        {persona.skills_proficiency && <RecordField label="Skills / proficiency" value={persona.skills_proficiency} />}
        {persona.frequency_of_use && <RecordField label="Frequency of use" value={persona.frequency_of_use} />}
        {persona.constraints && <RecordField label="Constraints" value={persona.constraints} />}

        <RecordFieldGroup label="Importance weight" gap="0.35rem">
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
        </RecordFieldGroup>

        <RecordPersonField
          label="Owner" ariaLabel="Persona owner" userId={persona.owner_id} orgUsers={orgUsers}
          organizationId={ownerOrgId} readOnly={readOnlyInProject}
          onChange={(ownerId) =>
            run(() => scopedApi.update(scopeId, persona.id, { owner_id: ownerId || null }), "Owner updated.", "Could not update this Persona's owner.")
          }
        />
        <RecordPersonField
          label="Champion (keeps this persona accurate)" ariaLabel="Persona champion" userId={persona.champion_id}
          orgUsers={orgUsers} organizationId={ownerOrgId} readOnly={readOnlyInProject}
          onChange={(championId) =>
            run(() => scopedApi.update(scopeId, persona.id, { champion_id: championId || null }), "Champion updated.", "Could not update this Persona's champion.")
          }
        />

        <RepresentationPanel
          heading="Represented by"
          emptyText="No Stakeholder represents this Persona yet."
          load={() => scopedApi.listStakeholders(scopeId, persona.id)}
          linkFor={(stakeholder) => `${projectId ? "/projects" : "/orgs"}/${scopeId}/modules/stakeholders/stakeholders/${stakeholder.id}`}
        />

        <HeldNeedsPanel projectId={projectId} load={() => projectNeedApi.listPersonaNeeds(projectId ?? "", persona.id)} />

        <RelationshipsPanel projectId={projectId} holder="persona" holderId={persona.id} />

        {!readOnlyInProject && (
          <RecordLifecycleControls
            noun="Persona"
            status={persona.status}
            isArchived={persona.is_archived}
            activateBody="An Active persona is offered as a target when scoring. A comment is optional."
            retireBody="A Retired persona is no longer offered when scoring, but keeps its history and can be reactivated. A comment is optional."
            archiveBody="This Persona will no longer appear in the active list or be offered when scoring. Nothing is deleted."
            onTransition={(action, comment) => run(() => scopedApi[action](scopeId, persona.id, comment), TRANSITION_DONE[action])}
            onArchiveToggle={() =>
              run(
                () => (persona.is_archived ? scopedApi.unarchive(scopeId, persona.id) : scopedApi.archive(scopeId, persona.id)),
                persona.is_archived ? "Persona unarchived." : "Persona archived.",
              )
            }
          />
        )}

        <VersionHistoryTable
          versions={versions}
          columns={[
            { header: "Status", render: (v) => PERSONA_STATUS_LABEL[v.status] },
            { header: "Weight", render: (v) => v.weight ?? "—" },
          ]}
        />

        <RecordDiscussion
          api={scopedApi}
          scopeId={scopeId}
          recordId={persona.id}
          noun="Persona"
          currentUserId={user?.id}
          attachmentsReadOnly={readOnlyInProject}
          attachmentsHint="Attachments to an organisation Persona are managed from the organisation view."
        />
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
    </div>
  );
}
