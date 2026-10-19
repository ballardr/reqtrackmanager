/**
 * Module: modules/stakeholders/EngagementFormModal
 *
 * Create/edit dialog for an Engagement's content fields (docs/ux-style-guide.md
 * principle 3: a full entity create/edit is a `Modal`). Shared by create, edit
 * (distinguished by whether `initial` is passed) and the "Log contact" quick
 * add. `compact` keeps only title, channel, date and summary for the quick add;
 * the rest (purpose, notes, consent, retain-until) is filled in from the detail
 * page. The facilitators and the people involved are assigned from the detail
 * page, so the form never needs a picker. Fields sit in a `FormGrid`: short ones in pairs, long ones full width. Channel renders through its label
 * map and every control has a visible label (principle 13).
 */
import { useState } from "react";

import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import type { CollectedLink } from "../../api/artefactLinks";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { CheckboxField, DateField, TextAreaField, TextField } from "../../components/FormFields";
import type { Engagement, EngagementChannel, EngagementFieldValues } from "./types";
import { ENGAGEMENT_CHANNEL_LABEL } from "./types";
import { FormActions } from "../../components/FormActions";
import { localToday } from "../../utils/localDate";

const CHANNEL_OPTIONS = Object.entries(ENGAGEMENT_CHANNEL_LABEL).map(([value, label]) => ({ value, label }));

export function EngagementFormModal({
  initial,
  projectId,
  defaults,
  heading,
  compact = false,
  error,
  onCancel,
  onSave,
}: {
  initial?: Engagement;
  /** The project a new engagement is logged in; with it a full create form offers the quick-link field (the compact quick add does not). */
  projectId?: string;
  /** Starting values for a new engagement (e.g. the quick add's suggested title). */
  defaults?: Partial<EngagementFieldValues>;
  /** Overrides the dialog title. */
  heading?: string;
  /** Show only title, channel, date and summary. */
  compact?: boolean;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: EngagementFieldValues, quickLinks: CollectedLink[], tags: string[]) => void;
}) {
  const seed = initial ?? defaults;
  const [title, setTitle] = useState(seed?.title ?? "");
  const [channel, setChannel] = useState<EngagementChannel>(seed?.channel ?? "meeting");
  const [date, setDate] = useState(seed?.engagement_date ?? localToday());
  const [purpose, setPurpose] = useState(seed?.purpose ?? "");
  const [summary, setSummary] = useState(seed?.summary ?? "");
  const [notes, setNotes] = useState(seed?.notes ?? "");
  const [consent, setConsent] = useState(seed?.consent_recorded ?? false);
  const [retainUntil, setRetainUntil] = useState(seed?.retain_until ?? "");
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);

  return (
    <Modal title={heading ?? (initial ? `Edit ${initial.title}` : "Log engagement")} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <FormGridFull>
            <TextField label="Title" ariaLabel="Engagement title" value={title} onChange={setTitle} hint="What happened, e.g. “Quarterly review with the regulator”." />
          </FormGridFull>
          <LabeledSelect
            label="Channel" value={channel} placeholder={null}
            onChange={(value) => setChannel(value as EngagementChannel)} options={CHANNEL_OPTIONS}
          />
          <DateField label="Date" value={date} onChange={setDate} />
          {!compact && (
            <FormGridFull>
              <TextAreaField label="Purpose" rows={2} value={purpose} onChange={setPurpose} hint="Why the engagement took place." />
            </FormGridFull>
          )}
          <FormGridFull>
            <TextAreaField label="Summary" rows={compact ? 3 : 2} value={summary} onChange={setSummary} hint="A line or two on the outcome." />
          </FormGridFull>
          {!compact && (
            <>
              <FormGridFull>
                <TextAreaField
                  label="Notes" rows={5} value={notes} onChange={setNotes}
                  hint="Notes can name people and are personal data: they are deleted with the engagement."
                />
              </FormGridFull>
              <CheckboxField
                heading="Consent" label="Recorded" ariaLabel="Consent recorded" checked={consent} onChange={setConsent}
                hint="Tick once the participants have agreed to being recorded here."
              />
              <DateField
                label="Retain until" value={retainUntil} onChange={setRetainUntil}
                hint="Optional. Nothing is deleted automatically; the engagement is flagged when this date is reached."
              />
            </>
          )}
          {!initial && !compact && projectId && (
            <FormGridFull>
              <div className="stack">
                <QuickLinkField projectId={projectId} artefactType="engagement" preferredType="stakeholder" value={quickLinks} onChange={setQuickLinks} />
                <TagField projectId={projectId} artefactType="engagement" value={tags} onChange={setTags} />
              </div>
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions
          error={error}
          onCancel={onCancel}
          onSave={() =>
            onSave({
              title: title.trim(), channel, engagement_date: date, purpose, summary, notes,
              consent_recorded: consent, retain_until: retainUntil === "" ? null : retainUntil,
            }, quickLinks, tags)}
        saveDisabled={title.trim() === "" || date === ""}
        />
      </div>
    </Modal>
  );
}
