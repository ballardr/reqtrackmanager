/**
 * Module: modules/stakeholders/StakeholderDetailPage
 *
 * A single Stakeholder's detail: fields, lifecycle, owner, Influence/Interest
 * position and engagement cadence, the Personas they represent, their needs, version
 * history, attachments, comments, and permanent deletion. One scope-aware
 * component serving three routes (`module.ts`): a project stakeholder and an
 * org stakeholder opened *from a project* (both `/projects/:projectId/...`),
 * and an org stakeholder opened from the org dashboard (`/orgs/:organizationId/
 * ...`). Mirrors `PersonaDetailPage`, built from the same shared parts.
 *
 * An org stakeholder viewed inside a project is read-only here apart from
 * comments (the project API can't mutate it); a link leads to the org route
 * where the owner role can edit it.
 *
 * Personal data: contact info is Confidential, so it sits behind the same
 * visibility as the record. "Delete permanently" (Phase 0 resolution 15) is
 * the module's one irreversible action, so it is a tier-2 `ConfirmDialog`
 * requiring the stakeholder's exact name to be typed, and says exactly what is
 * removed. Every mutating control always renders regardless of role; the
 * backend enforces `stakeholder_owner`/`org_stakeholder_owner` and a 403
 * surfaces as a toast.
 */
import { Pencil } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../../api/client";
import type { OrgUser, Project } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Spinner } from "../../components/Spinner";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import {
  orgPersonaApi, orgStakeholderApi, orgStakeholderTypeApi, projectNeedApi, projectPersonaApi, projectStakeholderApi,
} from "./api";
import { HeldNeedsPanel } from "./HeldNeedsPanel";
import { RecordField, RecordFieldGroup, RecordPersonField, VersionHistoryTable } from "./RecordDetailParts";
import { RecordDiscussion } from "./RecordDiscussion";
import { RecordLifecycleControls, type LifecycleAction } from "./RecordLifecycleControls";
import { RepresentationPanel } from "./RepresentationPanel";
import { StakeholderFormModal } from "./StakeholderFormModal";
import type { CadenceHint, Stakeholder, StakeholderFieldValues, StakeholderVersion } from "./types";
import {
  GRID_QUADRANT_LABEL, STAKEHOLDER_SCOPE_LABEL, STAKEHOLDER_STATUS_LABEL, STAKEHOLDER_STATUS_TONE, TARGET_CADENCE_LABEL,
} from "./types";
import { levelName, useStakeholderScheme } from "./useStakeholderScheme";

const TRANSITION_DONE: Record<LifecycleAction, string> = {
  activate: "Stakeholder activated.",
  retire: "Stakeholder retired.",
};

export function StakeholderDetailPage() {
  const { projectId, organizationId, stakeholderId } = useParams<{
    projectId?: string;
    organizationId?: string;
    stakeholderId: string;
  }>();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const scopedApi = projectId ? projectStakeholderApi : orgStakeholderApi;
  const scopeId = projectId ?? organizationId;
  const listPath = projectId ? `/projects/${projectId}/modules/stakeholders/stakeholders` : "/org-overview";
  const backLabel = projectId ? "← Stakeholders" : "← Organisation overview";

  const [stakeholder, setStakeholder] = useState<Stakeholder | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [versions, setVersions] = useState<StakeholderVersion[] | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [projectOrgId, setProjectOrgId] = useState<string | undefined>(undefined);
  const [typeOptions, setTypeOptions] = useState<{ value: string; label: string }[]>([]);
  const [personaOptions, setPersonaOptions] = useState<{ value: string; label: string }[]>([]);
  const [fetchedHint, setFetchedHint] = useState<{ key: string; hint: CadenceHint } | null>(null);
  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [erasing, setErasing] = useState(false);
  const scheme = useStakeholderScheme(projectId ? { projectId } : { orgId: organizationId ?? "" });

  // An org stakeholder opened inside a project can't be mutated through the project API.
  const readOnlyInProject = !!projectId && stakeholder?.scope === "organization";

  useEffect(() => {
    if (!scopeId || !stakeholderId) return;
    scopedApi.get(scopeId, stakeholderId).then(setStakeholder).catch((err) => {
      setLoadError(toErrorMessage(err, "This Stakeholder could not be found, or you don't have access to it."));
    });
    scopedApi.listVersions(scopeId, stakeholderId).then(setVersions).catch(() => setVersions([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeId, stakeholderId]);

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
    const types = projectId
      ? projectStakeholderApi.listTypes(scopeId).then((list) => list.filter((t) => t.is_enabled).map((t) => ({ value: t.id, label: t.name })))
      : orgStakeholderTypeApi.list(scopeId).then((list) => list.filter((t) => t.is_active).map((t) => ({ value: t.id, label: t.name })));
    types.then(setTypeOptions).catch(() => setTypeOptions([]));
    // The Personas this stakeholder could represent: the project's own and org's, or the org's alone.
    const personas = projectId ? projectPersonaApi.list(scopeId) : orgPersonaApi.list(scopeId);
    personas.then((list) => setPersonaOptions(list.map((p) => ({ value: p.id, label: p.name })))).catch(() => setPersonaOptions([]));
  }, [scopeId, projectId]);

  // The grid position and suggested cadence for the saved levels.
  // The hint only applies to the exact pair of levels it was fetched for, so a stale one never shows.
  const influenceId = stakeholder?.influence_level_id ?? null;
  const interestId = stakeholder?.interest_level_id ?? null;
  const hintKey = influenceId && interestId ? `${influenceId}:${interestId}` : null;
  const hint = fetchedHint && fetchedHint.key === hintKey ? fetchedHint.hint : null;
  useEffect(() => {
    if (!scopeId || !influenceId || !interestId) return;
    let active = true;
    const key = `${influenceId}:${interestId}`;
    scopedApi.cadenceHint(scopeId, influenceId, interestId).then((h) => active && setFetchedHint({ key, hint: h })).catch(() => undefined);
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeId, influenceId, interestId]);

  async function run(action: () => Promise<Stakeholder>, successMessage: string, errorMessage = "Could not update this Stakeholder.") {
    try {
      const updated = await action();
      showToast(successMessage);
      setStakeholder(updated);
      if (scopeId && stakeholderId) void scopedApi.listVersions(scopeId, stakeholderId).then(setVersions).catch(() => undefined);
    } catch (err) {
      showToast(toErrorMessage(err, errorMessage), "error");
    }
  }

  async function saveEdit(values: StakeholderFieldValues) {
    if (!scopeId || !stakeholder) return;
    setFormError(null);
    try {
      const updated = await scopedApi.update(scopeId, stakeholder.id, values);
      showToast("Stakeholder updated.");
      setEditing(false);
      setStakeholder(updated);
      void scopedApi.listVersions(scopeId, stakeholder.id).then(setVersions).catch(() => undefined);
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not update this Stakeholder."));
    }
  }

  async function erase() {
    if (!scopeId || !stakeholder) return;
    setErasing(false);
    try {
      await scopedApi.erase(scopeId, stakeholder.id);
      showToast("Stakeholder permanently deleted.");
      navigate(listPath);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not delete this Stakeholder."), "error");
    }
  }

  if (!scopeId || !stakeholderId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (stakeholder === null) return <Spinner />;

  const linkedUser = orgUsers.find((u) => u.user_id === stakeholder.user_id);

  return (
    <div className="container stack">
      <Link to={listPath}>{backLabel}</Link>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ margin: 0 }}>{stakeholder.name}</h1>
        <span className="row" style={{ gap: "0.5rem" }}>
          <span className="badge">{STAKEHOLDER_SCOPE_LABEL[stakeholder.scope]}</span>
          <span className={`badge badge--${STAKEHOLDER_STATUS_TONE[stakeholder.status]}`}>{STAKEHOLDER_STATUS_LABEL[stakeholder.status]}</span>
        </span>
      </div>

      <div className="stack">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <p className="text-muted" style={{ margin: 0 }}>
            {[stakeholder.stakeholder_type_name, stakeholder.role, stakeholder.organisation_group].filter(Boolean).join(" · ") || "No type or role set"} · v{stakeholder.version_number}
            {stakeholder.is_archived && " · Archived"}
          </p>
          {!readOnlyInProject && (
            <button className="btn" title="Edit" aria-label="Edit" onClick={() => setEditing(true)}>
              <Pencil size={14} />
            </button>
          )}
        </div>

        {readOnlyInProject && (
          <p className="text-muted" style={{ margin: 0 }}>
            This is an organisation-wide Stakeholder shared by every project. Edit it from the{" "}
            <Link to={`/orgs/${stakeholder.organization_id}/modules/stakeholders/stakeholders/${stakeholder.id}`}>organisation view</Link>.
          </p>
        )}

        {stakeholder.description && <RecordField label="Description" value={stakeholder.description} />}
        {stakeholder.interests && <RecordField label="Interests" value={stakeholder.interests} />}
        {stakeholder.responsibilities && <RecordField label="Responsibilities" value={stakeholder.responsibilities} />}
        {stakeholder.goals_needs && <RecordField label="Goals and needs" value={stakeholder.goals_needs} />}
        {stakeholder.priorities && <RecordField label="Priorities" value={stakeholder.priorities} />}
        {stakeholder.constraints && <RecordField label="Constraints" value={stakeholder.constraints} />}
        {stakeholder.workflows_scenarios && <RecordField label="Workflows / use scenarios" value={stakeholder.workflows_scenarios} />}
        {stakeholder.contact_info && <RecordField label="Contact / reference information" value={stakeholder.contact_info} />}

        <RecordFieldGroup label="Influence and interest">
          <span data-testid="grid-position">
            Influence: {levelName(scheme, "influence", stakeholder.influence_level_id)} · Interest: {levelName(scheme, "interest", stakeholder.interest_level_id)}
            {hint?.quadrant && ` · ${GRID_QUADRANT_LABEL[hint.quadrant]}`}
          </span>
        </RecordFieldGroup>

        <RecordFieldGroup label="Engagement">
          <span data-testid="cadence">
            Target cadence: {stakeholder.target_cadence ? TARGET_CADENCE_LABEL[stakeholder.target_cadence] : "Not set"}
            {hint?.suggested_cadence && hint.suggested_cadence !== stakeholder.target_cadence &&
              ` (suggested by their position: ${TARGET_CADENCE_LABEL[hint.suggested_cadence]})`}
          </span>
          {stakeholder.availability_constraints && (
            <span className="text-muted">Their availability: {stakeholder.availability_constraints}</span>
          )}
        </RecordFieldGroup>

        <RecordPersonField
          label="Owner" ariaLabel="Stakeholder owner" userId={stakeholder.owner_id} orgUsers={orgUsers}
          organizationId={ownerOrgId} readOnly={readOnlyInProject}
          onChange={(ownerId) =>
            run(() => scopedApi.update(scopeId, stakeholder.id, { owner_id: ownerId || null }), "Owner updated.", "Could not update this Stakeholder's owner.")
          }
        />
        {stakeholder.user_id && (
          <RecordFieldGroup label="Platform user">
            <span>{linkedUser?.display_name ?? "A platform user"}</span>
          </RecordFieldGroup>
        )}

        <RepresentationPanel
          heading="Represents these Personas"
          emptyText="This Stakeholder doesn't represent any Persona yet."
          load={() => scopedApi.listPersonas(scopeId, stakeholder.id)}
          linkFor={(persona) =>
            projectId
              ? `/projects/${projectId}/modules/stakeholders/personas/${persona.id}`
              : `/orgs/${scopeId}/modules/stakeholders/personas/${persona.id}`
          }
          edit={
            readOnlyInProject
              ? undefined
              : {
                  options: personaOptions,
                  pickerLabel: "Persona to represent",
                  onAdd: async (personaId) => {
                    await scopedApi.addPersona(scopeId, stakeholder.id, personaId);
                  },
                  onRemove: (persona) => scopedApi.removePersona(scopeId, stakeholder.id, persona.id),
                }
          }
        />

        <HeldNeedsPanel projectId={projectId} load={() => projectNeedApi.listStakeholderNeeds(projectId ?? "", stakeholder.id)} />

        {!readOnlyInProject && (
          <RecordLifecycleControls
            noun="Stakeholder"
            status={stakeholder.status}
            isArchived={stakeholder.is_archived}
            activateBody="An Active stakeholder is part of the current stakeholder register. A comment is optional."
            retireBody="A Retired stakeholder is no longer part of the current register, but keeps its history and can be reactivated. A comment is optional."
            archiveBody="This Stakeholder will no longer appear in the active list. Nothing is deleted."
            onTransition={(action, comment) => run(() => scopedApi[action](scopeId, stakeholder.id, comment), TRANSITION_DONE[action])}
            onArchiveToggle={() =>
              run(
                () => (stakeholder.is_archived ? scopedApi.unarchive(scopeId, stakeholder.id) : scopedApi.archive(scopeId, stakeholder.id)),
                stakeholder.is_archived ? "Stakeholder unarchived." : "Stakeholder archived.",
              )
            }
          >
            <button className="btn btn-danger" onClick={() => setErasing(true)}>Delete permanently</button>
          </RecordLifecycleControls>
        )}

        <VersionHistoryTable
          versions={versions}
          columns={[
            { header: "Status", render: (v) => STAKEHOLDER_STATUS_LABEL[v.status] },
            { header: "Cadence", render: (v) => (v.target_cadence ? TARGET_CADENCE_LABEL[v.target_cadence] : "—") },
          ]}
        />

        <RecordDiscussion
          api={scopedApi}
          scopeId={scopeId}
          recordId={stakeholder.id}
          noun="Stakeholder"
          currentUserId={user?.id}
          attachmentsReadOnly={readOnlyInProject}
          attachmentsHint="Attachments to an organisation Stakeholder are managed from the organisation view."
        />
      </div>

      {editing && (
        <StakeholderFormModal
          initial={stakeholder}
          scopeLabel={projectId ? "project" : "organisation"}
          typeOptions={typeOptions}
          scheme={scheme}
          loadHint={(influence, interest) => scopedApi.cadenceHint(scopeId, influence, interest)}
          error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }}
          onSave={saveEdit}
        />
      )}

      {erasing && (
        <ConfirmDialog
          title={`Permanently delete ${stakeholder.name}?`}
          message={
            "This cannot be undone. It deletes this Stakeholder's record, every version of it (including contact " +
            "information), its comments, its attachments and files, and its links to Personas. The audit trail " +
            "keeps only that a deletion happened, not who the person was."
          }
          confirmLabel="Delete permanently"
          requireTypedText={stakeholder.name}
          onConfirm={erase}
          onCancel={() => setErasing(false)}
        />
      )}
    </div>
  );
}
