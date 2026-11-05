/**
 * Module: modules/product_feedback/RequestFormModal
 *
 * Create/edit dialog for an enhancement request, shared by the project list, the organisation inbox and both
 * detail pages ("create-as-a-layer"). The fields are `RequestFields`, so create and edit cannot drift; an edit
 * also takes a change note, recorded with the new version. A create in a project also offers the quick-link
 * field (a requester, a Pain Point) and tags, applied by the page once the record exists; an inbox request has
 * no links or tags (those belong to a project) so it omits both. The owner shares a row with the tags (create) or the
 * change note (edit), and the scores of the chosen levels are shown live under the level pickers.
 */
import { useState } from "react";

import type { CollectedLink } from "../../api/artefactLinks";
import type { ScoringScheme } from "../../api/scoring";
import type { OrgUser } from "../../api/types";
import { FormActions } from "../../components/FormActions";
import { TextField } from "../../components/FormFields";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { Modal } from "../../components/Modal";
import { CollapsibleSection } from "../../components/CollapsibleSection";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { orgRequestApi, projectRequestApi } from "./api";
import { PRODUCT_FEEDBACK_HELP } from "./help";
import { RequestFields } from "./RequestFields";
import { BLANK_REQUEST_DRAFT, type RequestDraft } from "./requestDraft";
import { referencesPayload } from "./referenceDraft";
import { initialLevelDraft, levelsPayload, type LevelDraft } from "./requestLevels";
import { RequestersField } from "./RequestersField";
import { useExternalReferencesEnabled } from "./useExternalReferences";
import { useExternalSystemChoices } from "./useFeedbackLists";
import type { EnhancementRequest, EnhancementRequestCreate, EnhancementRequestUpdate, Requester } from "./types";

/** What the form hands back; `changeNote` is set on an edit only. */
export type RequestFormValues = EnhancementRequestCreate & Pick<EnhancementRequestUpdate, "change_note">;

/**
 * @param initial The request being edited; omit to create.
 * @param scopeLabel "project" or "organisation inbox", shown in a create form's title.
 * @param scheme The scoring scheme in effect, for the level fields.
 * @param orgUsers Organisation users offered as owner.
 * @param organizationId The owning organisation (user search, organisation groups).
 * @param projectId The project a new request is created in (quick links, tags, project groups); omit for the inbox.
 * @param error A save error to show beside the actions.
 * @param currentRequesters An edit's requesters so far (the Demand card's loaded page and the total), listed read-only above the
 *   field that adds more; removing one is the Links panel's.
 * @param onCancel Closes the form.
 * @param onSave Called with the values, the chosen quick links and the chosen tags.
 */
export function RequestFormModal({
  initial, scopeLabel, scheme, orgUsers, organizationId, projectId, error, currentRequesters, onCancel, onSave,
}: {
  initial?: EnhancementRequest;
  scopeLabel: string;
  scheme: ScoringScheme | null;
  orgUsers: OrgUser[];
  organizationId?: string;
  projectId?: string;
  error?: string | null;
  currentRequesters?: { requesters: Requester[]; total: number };
  onCancel: () => void;
  onSave: (values: RequestFormValues, quickLinks: CollectedLink[], tags: string[]) => void;
}) {
  const [draft, setDraft] = useState<RequestDraft>(() => initial ? {
    title: initial.title,
    description: initial.description,
    owner: initial.owner ? { type: initial.owner.type, id: initial.owner.id } : null,
    references: [],
    levels: initialLevelDraft(initial.levels),
  } : BLANK_REQUEST_DRAFT);
  const [changeNote, setChangeNote] = useState("");
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [requesters, setRequesters] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const systems = useExternalSystemChoices(projectId, organizationId);
  const referencesOn = useExternalReferencesEnabled(projectId, organizationId);

  function save() {
    onSave({
      title: draft.title.trim(),
      description: draft.description,
      owner: draft.owner,
      levels: levelsPayload(draft.levels, initial?.levels),
      ...(initial ? { change_note: changeNote } : { references: referencesPayload(draft.references) }),
    }, [...requesters, ...quickLinks], tags);
  }

  const previewScores = (levels: LevelDraft, requestId?: string) => projectId
    ? projectRequestApi.previewScores(projectId, levels, requestId)
    : orgRequestApi.previewScores(organizationId ?? "", levels);

  return (
    <Modal title={initial ? `Edit ${initial.title}` : `New enhancement request (${scopeLabel})`} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <RequestFields
            draft={draft} onChange={setDraft} scheme={scheme} derivedLevels={initial?.derived_levels}
            orgUsers={orgUsers} organizationId={organizationId} projectId={projectId} savedOwner={initial?.owner}
            systems={initial || !referencesOn ? undefined : systems} previewScores={scheme ? previewScores : undefined} requestId={initial?.id}
            beside={initial
              ? <TextField help={PRODUCT_FEEDBACK_HELP.changeNote} label="Change note" ariaLabel="Change note" value={changeNote} onChange={setChangeNote} />
              : projectId ? <TagField projectId={projectId} artefactType="enhancement_request" value={tags} onChange={setTags} /> : undefined}
          />
          {projectId && !initial && (
            <FormGridFull>
              <RequestersField projectId={projectId} value={requesters} onChange={setRequesters} />
            </FormGridFull>
          )}
          {projectId && initial && (
            <FormGridFull>
              <CollapsibleSection
                sectionKey="product_feedback_edit_requesters" variant="plain" defaultCollapsed title="Requesters"
                summary={currentRequesters ? `${currentRequesters.total} so far` : undefined}
              >
                <div className="stack" style={{ gap: "var(--space-2)" }}>
                  {currentRequesters && currentRequesters.total > 0 ? (
                    <div className="stack" style={{ gap: "var(--space-1)" }}>
                      <ul aria-label="Current requesters" style={{ margin: 0, paddingLeft: "1.2rem" }}>
                        {currentRequesters.requesters.map((r) => (
                          <li key={`${r.artefact_type}:${r.id}`}>
                            {r.hidden ? <span className="text-muted">A requester you can’t view</span> : r.label}
                            {(r.from_merge || r.via_engagement) && (
                              <span className="text-muted"> ({[r.from_merge && "merged duplicate", r.via_engagement && "via an Engagement"].filter(Boolean).join(", ")})</span>
                            )}
                          </li>
                        ))}
                      </ul>
                      {currentRequesters.requesters.length < currentRequesters.total && (
                        <span className="text-muted">Showing {currentRequesters.requesters.length} of {currentRequesters.total}; the Demand card lists them all.</span>
                      )}
                    </div>
                  ) : (
                    <span className="text-muted">No one is recorded as having asked for this yet.</span>
                  )}
                  <RequestersField
                    projectId={projectId} value={requesters} onChange={setRequesters} label="Add requesters" titled={false}
                    help="Added when you save. To remove one, use the Demand card."
                  />
                </div>
              </CollapsibleSection>
            </FormGridFull>
          )}
          {!initial && projectId && (
            <FormGridFull>
              <QuickLinkField projectId={projectId} artefactType="enhancement_request" preferredType="stakeholder" titled value={quickLinks} onChange={setQuickLinks} />
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={save} saveDisabled={draft.title.trim() === ""} />
      </div>
    </Modal>
  );
}
