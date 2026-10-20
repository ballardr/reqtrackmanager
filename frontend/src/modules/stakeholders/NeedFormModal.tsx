/**
 * Module: modules/stakeholders/NeedFormModal
 *
 * Create/edit dialog for a Stakeholder Need's content fields (docs/ux-style-
 * guide.md principle 3: a full entity create/edit is a `Modal`). Shared by
 * create and edit (distinguished by whether `initial` is passed). A need is
 * always project-scoped, so unlike the Persona/Stakeholder forms there is no
 * scope or type to choose. `owner` is assigned from the detail page through
 * `RecordPrincipalField`; `change_note` only renders when editing. Every field has a
 * visible label (principle 13).
 */
import { useState } from "react";

import type { CollectedLink } from "../../api/artefactLinks";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { TextAreaField, TextField } from "../../components/FormFields";
import type { Need, NeedFieldValues } from "./types";
import { FormActions } from "../../components/FormActions";

export function NeedFormModal({
  initial,
  projectId,
  error,
  onCancel,
  onSave,
}: {
  initial?: Need;
  /** The project the Need is created in; with it a create form offers the quick-link field. */
  projectId?: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: NeedFieldValues, quickLinks: CollectedLink[], tags: string[]) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [rationale, setRationale] = useState(initial?.rationale ?? "");
  const [changeNote, setChangeNote] = useState("");
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);

  return (
    <Modal title={initial ? `Edit ${initial.name}` : "New Stakeholder Need"} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <FormGridFull>
            <TextField helpNotNeeded required label="Name" ariaLabel="Need name" value={name} onChange={setName} hint="A short title, e.g. “Diagnose faults quickly”." />
          </FormGridFull>
          <FormGridFull>
            <TextAreaField helpNotNeeded
              label="Need" rows={3} value={description} onChange={setDescription}
              hint="The need in the stakeholder's own words, before it becomes a requirement."
            />
          </FormGridFull>
          <FormGridFull>
            <TextAreaField helpNotNeeded label="Rationale" rows={3} value={rationale} onChange={setRationale} hint="Why it matters, and where it came from." />
          </FormGridFull>
          {initial && <FormGridFull><TextField helpNotNeeded label="Change note" ariaLabel="Change note" value={changeNote} onChange={setChangeNote} /></FormGridFull>}
          {!initial && projectId && (
            <FormGridFull>
              <div className="stack">
                <QuickLinkField
                projectId={projectId} artefactType="stakeholder_need" preferredType="stakeholder" value={quickLinks}
                onChange={setQuickLinks}
              />
                <TagField projectId={projectId} artefactType="stakeholder_need" value={tags} onChange={setTags} />
              </div>
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions
          error={error}
          onCancel={onCancel}
          onSave={() => onSave({ name: name.trim(), description, rationale, change_note: changeNote }, quickLinks, tags)}
          onSaveAndActivate={
            initial ? undefined : () => onSave({ name: name.trim(), description, rationale, change_note: changeNote, activate: true }, quickLinks, tags)
          }
          saveDisabled={name.trim() === ""}
        />
      </div>
    </Modal>
  );
}
