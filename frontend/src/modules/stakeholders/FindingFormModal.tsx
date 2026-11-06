/**
 * Module: modules/stakeholders/FindingFormModal
 *
 * Create/edit dialog for one research Finding, shared by an engagement's Findings panel (create and edit) and the Links
 * panel's "Create new" (`CreateLinkedRecordDialogs`). A finding belongs to one engagement: the panel fixes it, and the
 * Links panel passes `engagementOptions` so the person chooses (pre-selected when the page record is an engagement).
 * Creating in a project (`projectId` given) also offers the quick-link and tag fields every create form of a linkable,
 * taggable type has; the caller applies them once the finding exists.
 */
import { useState } from "react";

import type { CollectedLink } from "../../api/artefactLinks";
import { FormActions } from "../../components/FormActions";
import { TextAreaField, TextField } from "../../components/FormFields";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import type { ResearchFinding } from "./types";

/** What the form collects besides the finding's own fields; a create form only. */
export interface FindingExtras {
  /** The engagement chosen when `engagementOptions` was given; "" otherwise. */
  engagementId: string;
  quickLinks: CollectedLink[];
  tags: string[];
}

/**
 * @param initial The finding being edited; omit to create.
 * @param projectId The project a new finding is created in; with it a create form offers quick links and tags.
 * @param engagementOptions The engagements a new finding can belong to, when the form must ask; omit when fixed.
 * @param defaultEngagementId The engagement selected at first.
 * @param error A save error to show.
 * @param onCancel Called when the dialog is dismissed.
 * @param onSave Called with the finding's fields and the create-only extras.
 */
export function FindingFormModal({
  initial, projectId, engagementOptions, defaultEngagementId = "", error, onCancel, onSave,
}: {
  initial?: ResearchFinding;
  projectId?: string;
  engagementOptions?: { value: string; label: string }[];
  defaultEngagementId?: string;
  error: string | null;
  onCancel: () => void;
  onSave: (values: { title: string; description: string }, extras: FindingExtras) => void;
}) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [engagementId, setEngagementId] = useState(defaultEngagementId);
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const needsEngagement = !initial && engagementOptions !== undefined;
  return (
    <Modal title={initial ? `Edit ${initial.title}` : "New finding"} onClose={onCancel} size="lg">
      <div className="stack">
        {needsEngagement && (
          <LabeledSelect helpNotNeeded required
            label="Engagement" value={engagementId} onChange={setEngagementId} options={engagementOptions}
            placeholder={engagementOptions.length === 0 ? "No engagements logged yet" : "Choose an engagement"}
          />
        )}
        <TextField helpNotNeeded required label="Title" ariaLabel="Finding title" value={title} onChange={setTitle} hint="One line, e.g. “Technicians skip the checklist when offline”." />
        <TextAreaField helpNotNeeded label="Description" rows={5} value={description} onChange={setDescription} hint="Findings can quote participants and are deleted with the engagement." />
        {!initial && projectId && (
          <div className="stack">
            <QuickLinkField projectId={projectId} artefactType="research_finding" value={quickLinks} onChange={setQuickLinks} />
            <TagField projectId={projectId} artefactType="research_finding" value={tags} onChange={setTags} />
          </div>
        )}
        <FormActions
          error={error}
          onCancel={onCancel}
          onSave={() => onSave({ title: title.trim(), description }, { engagementId, quickLinks, tags })}
          saveDisabled={title.trim() === "" || (needsEngagement && engagementId === "")}
        />
      </div>
    </Modal>
  );
}
