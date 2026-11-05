/**
 * Module: modules/product_feedback/RequestFormModal
 *
 * Create/edit dialog for an enhancement request, shared by the project list, the organisation inbox and both
 * detail pages ("create-as-a-layer"). The fields are `RequestFields`, so create and edit cannot drift; an edit
 * also takes a change note, recorded with the new version. A create in a project also offers the quick-link
 * field (a requester, a Pain Point) and tags, applied by the page once the record exists; an inbox request has
 * no links or tags (those belong to a project) so it omits both.
 */
import { useState } from "react";

import type { CollectedLink } from "../../api/artefactLinks";
import type { ScoringScheme } from "../../api/scoring";
import type { OrgUser } from "../../api/types";
import { FormActions } from "../../components/FormActions";
import { TextField } from "../../components/FormFields";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { RequestFields } from "./RequestFields";
import { BLANK_REQUEST_DRAFT, type RequestDraft } from "./requestDraft";
import { referencesPayload } from "./referenceDraft";
import { initialLevelDraft, levelsPayload } from "./requestLevels";
import { useExternalSystemChoices } from "./useFeedbackLists";
import type { EnhancementRequest, EnhancementRequestCreate, EnhancementRequestUpdate } from "./types";

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
 * @param onCancel Closes the form.
 * @param onSave Called with the values, the chosen quick links and the chosen tags.
 */
export function RequestFormModal({
  initial, scopeLabel, scheme, orgUsers, organizationId, projectId, error, onCancel, onSave,
}: {
  initial?: EnhancementRequest;
  scopeLabel: string;
  scheme: ScoringScheme | null;
  orgUsers: OrgUser[];
  organizationId?: string;
  projectId?: string;
  error?: string | null;
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
  const [tags, setTags] = useState<string[]>([]);
  const systems = useExternalSystemChoices(projectId, organizationId);

  function save() {
    onSave({
      title: draft.title.trim(),
      description: draft.description,
      owner: draft.owner,
      levels: levelsPayload(draft.levels, initial?.levels),
      ...(initial ? { change_note: changeNote } : { references: referencesPayload(draft.references) }),
    }, quickLinks, tags);
  }

  return (
    <Modal title={initial ? `Edit ${initial.title}` : `New enhancement request (${scopeLabel})`} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <RequestFields
            draft={draft} onChange={setDraft} scheme={scheme} derivedLevels={initial?.derived_levels}
            orgUsers={orgUsers} organizationId={organizationId} projectId={projectId} savedOwner={initial?.owner}
            systems={initial ? undefined : systems}
          />
          {initial && (
            <FormGridFull>
              <TextField helpNotNeeded label="Change note" ariaLabel="Change note" value={changeNote} onChange={setChangeNote} />
            </FormGridFull>
          )}
          {!initial && projectId && (
            <FormGridFull>
              <div className="stack">
                <QuickLinkField projectId={projectId} artefactType="enhancement_request" preferredType="stakeholder" value={quickLinks} onChange={setQuickLinks} />
                <TagField projectId={projectId} artefactType="enhancement_request" value={tags} onChange={setTags} />
              </div>
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={save} saveDisabled={draft.title.trim() === ""} />
      </div>
    </Modal>
  );
}
