/**
 * Module: modules/stakeholders/NeedDetailPage
 *
 * A single Stakeholder Need's detail (`/projects/:projectId/modules/
 * stakeholders/needs/:needId`): the need and its rationale, lifecycle, owner,
 * the Stakeholders and Personas that have it ("has need"), the Requirements it
 * gave rise to ("gives rise to"), version history, attachments and comments.
 * Built from the same shared parts as `StakeholderDetailPage`; the link lists
 * are `RepresentationPanel`s. A need is project-scoped only, so there is no
 * org route and no read-only-in-project case.
 *
 * Every mutating control always renders regardless of role; the backend
 * enforces `stakeholder_need_owner` and a 403 surfaces as a toast.
 */
import { Pencil } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../../api/client";
import type { OrgUser, Project, Requirement } from "../../api/types";
import { Spinner } from "../../components/Spinner";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectNeedApi, projectPersonaApi, projectStakeholderApi } from "./api";
import { NeedFormModal } from "./NeedFormModal";
import { RecordField, RecordPersonField, VersionHistoryTable } from "./RecordDetailParts";
import { RecordDiscussion } from "./RecordDiscussion";
import { RecordLifecycleControls, type LifecycleAction } from "./RecordLifecycleControls";
import { RepresentationPanel } from "./RepresentationPanel";
import type { Need, NeedFieldValues, NeedHolderKind, NeedVersion } from "./types";
import { NEED_STATUS_LABEL, NEED_STATUS_TONE } from "./types";

const TRANSITION_DONE: Record<LifecycleAction, string> = {
  activate: "Stakeholder Need activated.",
  retire: "Stakeholder Need retired.",
};

type Option = { value: string; label: string };

export function NeedDetailPage() {
  const { projectId, needId } = useParams<{ projectId: string; needId: string }>();
  const { user } = useAuth();
  const { showToast } = useToast();
  const [need, setNeed] = useState<Need | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [versions, setVersions] = useState<NeedVersion[] | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [organizationId, setOrganizationId] = useState<string | undefined>(undefined);
  const [stakeholderOptions, setStakeholderOptions] = useState<Option[]>([]);
  const [personaOptions, setPersonaOptions] = useState<Option[]>([]);
  const [requirementOptions, setRequirementOptions] = useState<Option[]>([]);
  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId || !needId) return;
    projectNeedApi.get(projectId, needId).then(setNeed).catch((err) => {
      setLoadError(toErrorMessage(err, "This Stakeholder Need could not be found, or you don't have access to it."));
    });
    projectNeedApi.listVersions(projectId, needId).then(setVersions).catch(() => setVersions([]));
  }, [projectId, needId]);

  useEffect(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then((p) => setOrganizationId(p.organization_id)).catch(() => undefined);
    // Candidates for the link pickers: the project's visible Stakeholders/Personas and its Requirements.
    projectStakeholderApi.list(projectId).then((list) => setStakeholderOptions(list.map((s) => ({ value: s.id, label: s.name })))).catch(() => setStakeholderOptions([]));
    projectPersonaApi.list(projectId).then((list) => setPersonaOptions(list.map((p) => ({ value: p.id, label: p.name })))).catch(() => setPersonaOptions([]));
    api
      .get<Requirement[]>(`/api/v1/projects/${projectId}/requirements`)
      .then((list) => setRequirementOptions(list.map((r) => ({ value: r.id, label: `${r.unique_code} ${r.name}` }))))
      .catch(() => setRequirementOptions([]));
  }, [projectId]);

  useEffect(() => {
    if (!organizationId) return;
    api.get<OrgUser[]>(`/api/v1/orgs/${organizationId}/users`).then(setOrgUsers).catch(() => setOrgUsers([]));
  }, [organizationId]);

  async function run(action: () => Promise<Need>, successMessage: string, errorMessage = "Could not update this Stakeholder Need.") {
    if (!projectId || !needId) return;
    try {
      const updated = await action();
      showToast(successMessage);
      setNeed(updated);
      void projectNeedApi.listVersions(projectId, needId).then(setVersions).catch(() => undefined);
    } catch (err) {
      showToast(toErrorMessage(err, errorMessage), "error");
    }
  }

  async function saveEdit(values: NeedFieldValues) {
    if (!projectId || !need) return;
    setFormError(null);
    try {
      const updated = await projectNeedApi.update(projectId, need.id, values);
      showToast("Stakeholder Need updated.");
      setEditing(false);
      setNeed(updated);
      void projectNeedApi.listVersions(projectId, need.id).then(setVersions).catch(() => undefined);
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not update this Stakeholder Need."));
    }
  }

  if (!projectId || !needId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (need === null) return <Spinner />;

  const holderPanel = (kind: NeedHolderKind, heading: string, emptyText: string, pickerLabel: string, options: Option[]) => (
    <RepresentationPanel
      heading={heading}
      emptyText={emptyText}
      load={async () => (await projectNeedApi.listHolders(projectId, need.id)).filter((h) => h.kind === kind)}
      linkFor={(holder) => `/projects/${projectId}/modules/stakeholders/${kind === "stakeholder" ? "stakeholders" : "personas"}/${holder.id}`}
      edit={{
        options,
        pickerLabel,
        onAdd: async (id) => {
          await projectNeedApi.addHolder(projectId, need.id, kind, id);
        },
        onRemove: (holder) => projectNeedApi.removeHolder(projectId, need.id, kind, holder.id),
      }}
    />
  );

  return (
    <div className="container stack">
      <Link to={`/projects/${projectId}/modules/stakeholders/needs`}>← Needs</Link>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ margin: 0 }}>{need.name}</h1>
        <span className={`badge badge--${NEED_STATUS_TONE[need.status]}`}>{NEED_STATUS_LABEL[need.status]}</span>
      </div>

      <div className="stack">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <p className="text-muted" style={{ margin: 0 }}>
            v{need.version_number}
            {need.is_archived && " · Archived"}
          </p>
          <button className="btn" title="Edit" aria-label="Edit" onClick={() => setEditing(true)}>
            <Pencil size={14} />
          </button>
        </div>

        {need.description && <RecordField label="Need" value={need.description} />}
        {need.rationale && <RecordField label="Rationale" value={need.rationale} />}

        <RecordPersonField
          label="Owner" ariaLabel="Need owner" userId={need.owner_id} orgUsers={orgUsers} organizationId={organizationId}
          readOnly={false}
          onChange={(ownerId) =>
            run(() => projectNeedApi.update(projectId, need.id, { owner_id: ownerId || null }), "Owner updated.", "Could not update this Stakeholder Need's owner.")
          }
        />

        {holderPanel("stakeholder", "Stakeholders with this need", "No Stakeholder has this need yet.", "Stakeholder with this need", stakeholderOptions)}
        {holderPanel("persona", "Personas with this need", "No Persona has this need yet.", "Persona with this need", personaOptions)}

        <RepresentationPanel
          heading="Requirements it gave rise to"
          emptyText="No Requirement has come from this need yet."
          load={async () =>
            (await projectNeedApi.listRequirements(projectId, need.id)).map((r) => ({
              link_id: r.link_id, id: r.id, name: `${r.unique_code} ${r.title}`, scope: "project" as const,
            }))
          }
          linkFor={(requirement) => `/projects/${projectId}/requirements/${requirement.id}`}
          edit={{
            options: requirementOptions,
            pickerLabel: "Requirement it gave rise to",
            onAdd: async (requirementId) => {
              await projectNeedApi.addRequirement(projectId, need.id, requirementId);
            },
            onRemove: (requirement) => projectNeedApi.removeRequirement(projectId, need.id, requirement.id),
          }}
        />

        <RecordLifecycleControls
          noun="Stakeholder Need"
          status={need.status}
          isArchived={need.is_archived}
          activateBody="An Active need is part of the current set of stakeholder needs. A comment is optional."
          retireBody="A Retired need is no longer current, but keeps its history and links and can be reactivated. A comment is optional."
          archiveBody="This Stakeholder Need will no longer appear in the active list. Nothing is deleted."
          onTransition={(action, comment) => run(() => projectNeedApi[action](projectId, need.id, comment), TRANSITION_DONE[action])}
          onArchiveToggle={() =>
            run(
              () => (need.is_archived ? projectNeedApi.unarchive(projectId, need.id) : projectNeedApi.archive(projectId, need.id)),
              need.is_archived ? "Stakeholder Need unarchived." : "Stakeholder Need archived.",
            )
          }
        />

        <VersionHistoryTable versions={versions} columns={[{ header: "Status", render: (v) => NEED_STATUS_LABEL[v.status] }]} />

        <RecordDiscussion
          api={projectNeedApi}
          scopeId={projectId}
          recordId={need.id}
          noun="Stakeholder Need"
          currentUserId={user?.id}
          attachmentsReadOnly={false}
        />
      </div>

      {editing && (
        <NeedFormModal
          initial={need}
          error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }}
          onSave={saveEdit}
        />
      )}
    </div>
  );
}
