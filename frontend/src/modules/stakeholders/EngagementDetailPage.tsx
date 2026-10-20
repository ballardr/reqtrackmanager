/**
 * Module: modules/stakeholders/EngagementDetailPage
 *
 * A single Engagement (`/projects/:projectId/modules/stakeholders/engagements/
 * :engagementId`): what happened (channel, date, purpose, summary, notes), who
 * was involved (facilitators, Stakeholder participants, groups it was aimed at,
 * Personas covered), what it produced (Pain Points, Needs and Open Questions it
 * raised or answered) and, when the project has the research extras on, its
 * session prompts, anonymous participants and findings. Attachments and comments
 * are the shared `RecordDiscussion`.
 *
 * An engagement is project-scoped, edited in place and has no lifecycle or
 * version history; the one irreversible action is "Delete permanently", a tier-2 `ConfirmDialog` that requires typing the exact title
 * and says what goes with it. Every mutating control always renders regardless of
 * role; the backend enforces `engagement_owner` and a 403 surfaces as a toast.
 * The retain-until date only flags the engagement as due for review; nothing is
 * deleted automatically.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../../api/client";
import type { OrgUser, Project } from "../../api/types";
import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { RecordActivity } from "../../components/RecordActivity";
import { RecordTags } from "../../components/RecordTags";
import { DetailLayout } from "../../components/DetailLayout";
import { FormGrid } from "../../components/FormGrid";
import { PrincipalListField } from "../../components/PrincipalListField";
import { RecordField, RecordFieldGroup } from "../../components/RecordDetailParts";
import { RecordDiscussion } from "../../components/RecordDiscussion";
import { RecordHeader } from "../../components/RecordHeader";
import { useConfirmedAction } from "../../components/useConfirmedAction";
import { Spinner } from "../../components/Spinner";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectEngagementApi, projectPersonaApi, projectStakeholderApi, projectStakeholderGroupApi } from "./api";
import { AnonymousParticipantsPanel } from "./AnonymousParticipantsPanel";
import { EngagementAudiencePanel } from "./EngagementAudiencePanel";
import { EngagementFormModal } from "./EngagementFormModal";
import { EngagementOutcomesPanel } from "./EngagementOutcomesPanel";
import { RepresentationPanel } from "./RepresentationPanel";
import { ResearchFindingsPanel } from "./ResearchFindingsPanel";
import { ResearchPromptsPanel } from "./ResearchPromptsPanel";
import type { Engagement, EngagementFieldValues, OutcomeTargetType, StakeholderGroup } from "./types";
import { ENGAGEMENT_CHANNEL_LABEL } from "./types";
import { useResearchExtras } from "./useResearchExtras";
import { Badge } from "../../components/Badge";

type Option = { value: string; label: string };

/** The findings are listed in full below, so the Links panel starts with that group collapsed. */
const COLLAPSED_LINK_TYPES = ["research_finding"] as const;

export function EngagementDetailPage() {
  const { projectId, engagementId } = useParams<{ projectId: string; engagementId: string }>();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [engagement, setEngagement] = useState<Engagement | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [organizationId, setOrganizationId] = useState<string | undefined>(undefined);
  const [stakeholderOptions, setStakeholderOptions] = useState<Option[]>([]);
  const [personaOptions, setPersonaOptions] = useState<Option[]>([]);
  const [groups, setGroups] = useState<StakeholderGroup[]>([]);
  const [participantsKey, setParticipantsKey] = useState(0);
  // Bumped when a list on the page changes a link, so the Links panel beside it reloads.
  const [linksKey, setLinksKey] = useState(0);
  const linksChanged = () => setLinksKey((k) => k + 1);
  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const researchExtras = useResearchExtras(projectId);

  useEffect(() => {
    if (!projectId || !engagementId) return;
    projectEngagementApi.get(projectId, engagementId).then(setEngagement).catch((err) => {
      setLoadError(toErrorMessage(err, "This Engagement could not be found, or you don't have access to it."));
    });
  }, [projectId, engagementId]);

  useEffect(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then((p) => setOrganizationId(p.organization_id)).catch(() => undefined);
    projectStakeholderApi.list(projectId).then((list) => setStakeholderOptions(list.map((s) => ({ value: s.id, label: s.name })))).catch(() => setStakeholderOptions([]));
    projectPersonaApi.list(projectId).then((list) => setPersonaOptions(list.map((p) => ({ value: p.id, label: p.name })))).catch(() => setPersonaOptions([]));
    projectStakeholderGroupApi.list(projectId).then(setGroups).catch(() => setGroups([]));
  }, [projectId]);

  useEffect(() => {
    if (!organizationId) return;
    api.get<OrgUser[]>(`/api/v1/orgs/${organizationId}/users`).then(setOrgUsers).catch(() => setOrgUsers([]));
  }, [organizationId]);

  async function save(values: Parameters<typeof projectEngagementApi.update>[2], success: string, failure: string): Promise<boolean> {
    if (!projectId || !engagement) return false;
    try {
      const updated = await projectEngagementApi.update(projectId, engagement.id, values);
      showToast(success);
      setEngagement(updated);
      return true;
    } catch (err) {
      showToast(toErrorMessage(err, failure), "error");
      return false;
    }
  }

  async function saveEdit(values: EngagementFieldValues) {
    if (!projectId || !engagement) return;
    setFormError(null);
    try {
      const updated = await projectEngagementApi.update(projectId, engagement.id, values);
      showToast("Engagement updated.");
      setEditing(false);
      setEngagement(updated);
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not update this Engagement."));
    }
  }

  async function erase() {
    if (!projectId || !engagement) return;
    try {
      await projectEngagementApi.erase(projectId, engagement.id);
      showToast("Engagement permanently deleted.");
      navigate(`/projects/${projectId}/modules/stakeholders/engagements`);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not delete this Engagement."), "error");
    }
  }

  const eraseAction = useConfirmedAction({
    label: "Delete permanently",
    danger: true,
    hidden: !engagement,
    title: `Permanently delete ${engagement?.title ?? "this Engagement"}?`,
    message:
      "This cannot be undone. It deletes this engagement's record and notes, its participants and covered " +
      "Personas, any session prompts, anonymous participants and findings, its comments, and its attachments and files. " +
      "The audit trail keeps only that a deletion happened, not what was said.",
    requireTypedText: engagement?.title,
    onConfirm: erase,
  });

  if (!projectId || !engagementId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (engagement === null) return <Spinner />;

  const stakeholderPath = (id: string) => `/projects/${projectId}/modules/stakeholders/stakeholders/${id}`;
  const personaPath = (id: string) => `/projects/${projectId}/modules/stakeholders/personas/${id}`;

  return (
    <DetailLayout
      activity={projectId ? <RecordActivity projectId={projectId} artefactType="engagement" artefactId={engagement.id} refreshToken={linksKey} /> : undefined}
      aside={<ArtefactLinksPanel projectId={projectId} artefactType="engagement" artefactId={engagement.id} collapsedTypes={COLLAPSED_LINK_TYPES} refreshToken={linksKey} />}
    >
      <RecordHeader
        recordLabel="Engagement"
        title={engagement.title}
        code={engagement.unique_code}
        tags={projectId ? <RecordTags projectId={projectId} artefactType="engagement" artefactId={engagement.id} /> : undefined}
        back={{ to: `/projects/${projectId}/modules/stakeholders/engagements`, label: "← Engagements" }}
        badges={
          <>
            <Badge>{ENGAGEMENT_CHANNEL_LABEL[engagement.channel]}</Badge>
            {engagement.retention_due && <Badge tone="warning">Retention review due</Badge>}
          </>
        }
        subtitle={engagement.engagement_date}
        onEdit={() => setEditing(true)}
        actions={[eraseAction.item]}
      />
      {eraseAction.dialog}

      <div className="stack">
        {engagement.purpose && <RecordField label="Purpose" value={engagement.purpose} />}
        {engagement.summary && <RecordField label="Summary" value={engagement.summary} />}
        {engagement.notes && <RecordField label="Notes" value={engagement.notes} />}

        <FormGrid>
          <PrincipalListField
            label="Facilitators" ariaLabel="Engagement facilitator" values={engagement.facilitators} orgUsers={orgUsers}
            organizationId={organizationId} projectId={projectId} emptyText="Nobody is recorded as running it."
            onChange={(facilitators) => save({ facilitators }, "Facilitators updated.", "Could not update this Engagement's facilitators.")}
          />

          <RecordFieldGroup helpNotNeeded label="Consent and retention">
            <span data-testid="consent">Consent recorded: {engagement.consent_recorded ? "Yes" : "No"}</span>
            <span data-testid="retention">
              {engagement.retain_until ? `Retain until ${engagement.retain_until}` : "No retain-until date"}
              {engagement.retention_due && " · the date has been reached: review and delete if no longer needed"}
            </span>
          </RecordFieldGroup>

        </FormGrid>

        <FormGrid>
          <RepresentationPanel
            heading="Participants"
            emptyText="No Stakeholders are recorded as taking part."
            reloadKey={participantsKey}
            onChanged={linksChanged}
            load={async () =>
              (await projectEngagementApi.listParticipants(projectId, engagement.id)).map((p) => ({
                link_id: p.link_id, id: p.stakeholder_id, name: p.name, scope: p.scope, unique_code: p.unique_code, organization_id: p.organization_id,
              }))
            }
            linkFor={(participant) => stakeholderPath(participant.id)}
            edit={{
              options: stakeholderOptions,
              pickerLabel: "Stakeholder to add",
              onAdd: async (stakeholderId) => {
                await projectEngagementApi.addParticipant(projectId, engagement.id, stakeholderId);
              },
              onRemove: (participant) => projectEngagementApi.removeParticipant(projectId, engagement.id, participant.id),
            }}
          />

          <RepresentationPanel
            heading="Personas covered"
            onChanged={linksChanged}
            emptyText="No Persona is recorded as covered."
            load={async () =>
              (await projectEngagementApi.listPersonas(projectId, engagement.id)).map((p) => ({
                link_id: p.link_id, id: p.persona_id, name: p.name, scope: p.scope, unique_code: p.unique_code, organization_id: p.organization_id,
              }))
            }
            linkFor={(persona) => personaPath(persona.id)}
            edit={{
              options: personaOptions,
              pickerLabel: "Persona covered",
              onAdd: async (personaId) => {
                await projectEngagementApi.addPersona(projectId, engagement.id, personaId);
              },
              onRemove: (persona) => projectEngagementApi.removePersona(projectId, engagement.id, persona.id),
            }}
          />

          <EngagementAudiencePanel
            projectId={projectId}
            engagementId={engagement.id}
            groups={groups}
            onParticipantsChanged={() => setParticipantsKey((k) => k + 1)}
            onChanged={linksChanged}
          />

        </FormGrid>

        {researchExtras && <AnonymousParticipantsPanel projectId={projectId} engagementId={engagement.id} personaOptions={personaOptions} />}

        {researchExtras && <ResearchPromptsPanel projectId={projectId} engagementId={engagement.id} />}

        <EngagementOutcomesPanel
          projectId={projectId}
          holderId={engagement.id}
          api={projectEngagementApi.outcomes}
          loadTargets={(targetType: OutcomeTargetType) => projectEngagementApi.listOutcomeTargets(projectId, targetType)}
          onChanged={linksChanged}
        />

        {researchExtras && <ResearchFindingsPanel projectId={projectId} engagementId={engagement.id} onChanged={linksChanged} />}

        <RecordDiscussion
          api={projectEngagementApi}
          scopeId={projectId}
          recordId={engagement.id}
          noun="Engagement"
          currentUserId={user?.id}
          attachmentsReadOnly={false}
        />
      </div>

      {editing && (
        <EngagementFormModal
          initial={engagement}
          error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }}
          onSave={saveEdit}
        />
      )}

    </DetailLayout>
  );
}
