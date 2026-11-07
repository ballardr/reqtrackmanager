/**
 * Module: components/ActionFormModal
 *
 * The "New action" dialog: the shared `ActionFields` with the quick-link and tag fields every create form of a linkable,
 * taggable type has, in a `Modal` whose header holds Cancel and Create. Used by the Actions page and by the Links panel's
 * "Create new" (`CreateActionDialog`), so a field added to an action reaches both. The caller creates the record.
 */
import { useState } from "react";

import type { CollectedLink } from "../api/artefactLinks";
import type { ActionTypeDefinition, OrgUser, PrincipalRef } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { ActionFields, type ActionFieldValues } from "./ActionFields";
import { FormActions } from "./FormActions";
import { Modal } from "./Modal";
import { QuickLinkField } from "./QuickLinkField";
import { TagField } from "./TagField";

/** The fields of a new action as the create endpoint takes them. */
export interface NewActionValues {
  title: string;
  description: string;
  action_type_id: string;
  assignee: PrincipalRef | null;
  due_date: string | null;
}

/**
 * @param projectId The project the action is created in.
 * @param actionTypes The project's effective action types; the first is chosen at first.
 * @param orgUsers Organisation members offered by the assignee picker.
 * @param organizationId The organisation, for user search and organisation groups.
 * @param error A save error to show.
 * @param onCancel Called when the dialog is dismissed.
 * @param onSave Called with the action's fields, the chosen quick links and the chosen tags.
 */
export function ActionFormModal({
  projectId, actionTypes, orgUsers, organizationId, error, onCancel, onSave,
}: {
  projectId: string;
  actionTypes: ActionTypeDefinition[];
  orgUsers: OrgUser[];
  organizationId?: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: NewActionValues, quickLinks: CollectedLink[], tags: string[]) => void;
}) {
  const strings = useStrings();
  const [values, setValues] = useState<ActionFieldValues>({
    title: "", description: "", actionTypeId: actionTypes[0]?.id ?? "", assignee: null, dueDate: "",
  });
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  // The types may finish loading after the form opens; until one is chosen the select shows (and a save uses) the first.
  const actionTypeId = values.actionTypeId || actionTypes[0]?.id || "";
  const valid = values.title.trim() !== "" && actionTypeId !== "";
  return (
    <Modal title={strings.actions.newAction} onClose={onCancel} size="lg">
      <div className="stack">
        <ActionFields
          values={{ ...values, actionTypeId }} onChange={setValues} actionTypes={actionTypes} orgUsers={orgUsers}
          organizationId={organizationId} projectId={projectId}
        />
        <QuickLinkField projectId={projectId} artefactType="requirement_action" preferredType="requirement" value={quickLinks} onChange={setQuickLinks} />
        <TagField projectId={projectId} artefactType="requirement_action" value={tags} onChange={setTags} />
        <FormActions
          error={error} onCancel={onCancel} saveLabel={strings.common.create} saveDisabled={!valid}
          onSave={() => onSave({
            title: values.title, description: values.description, action_type_id: actionTypeId,
            assignee: values.assignee, due_date: values.dueDate || null,
          }, quickLinks, tags)}
        />
      </div>
    </Modal>
  );
}
