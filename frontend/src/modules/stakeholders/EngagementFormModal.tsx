/**
 * Module: modules/stakeholders/EngagementFormModal
 *
 * Create/edit dialog for an Engagement's content fields (docs/ux-style-guide.md
 * principle 3: a full entity create/edit is a `Modal`). Shared by create, edit
 * (distinguished by whether `initial` is passed) and the "Log contact" quick
 * add. `compact` keeps only title, channel, date and summary for the quick add;
 * the rest (purpose, notes, consent, retain-until) is filled in from the detail
 * page. A full form also holds the participants (`ParticipantsField`): a new engagement sends them as
 * `stakeholder_ids` and `anonymous_participants`; an edit is given the recorded ones as
 * `initialParticipants` and returns the complete edited lists, which the caller compares with
 * what was recorded. Quick links and tags are for a new engagement only; facilitators, covered
 * Personas and audience groups are assigned from the detail page.
 * Fields sit in a `FormGrid`: short ones in pairs, long ones full width. Channel
 * renders through its label map and every control has a visible label
 * (principle 13).
 */
import { useState } from "react";

import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import type { CollectedLink } from "../../api/artefactLinks";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { CheckboxField, DateField, TextAreaField, TextField } from "../../components/FormFields";
import { STAKEHOLDERS_HELP } from "./help";
import type { EngagementCreateValues } from "./api";
import type { AnonymousParticipantEntry, Engagement, EngagementChannel, EngagementFieldValues, ParticipantEntries } from "./types";
import { ENGAGEMENT_CHANNEL_LABEL } from "./types";
import { FormActions } from "../../components/FormActions";
import { ParticipantsField } from "./ParticipantsField";
import { localToday } from "../../utils/localDate";

const CHANNEL_OPTIONS = Object.entries(ENGAGEMENT_CHANNEL_LABEL).map(([value, label]) => ({ value, label }));

export function EngagementFormModal({
  initial,
  initialParticipants,
  projectId,
  defaults,
  heading,
  compact = false,
  error,
  onCancel,
  onSave,
}: {
  initial?: Engagement;
  /** An edit only: the participants recorded now. Without it (they could not be read) the edit form has no Participants field. */
  initialParticipants?: ParticipantEntries;
  /** The project of the engagement. For a new engagement is logged in; with it a full create form offers the quick-link field (the compact quick add does not). */
  projectId?: string;
  /** Starting values for a new engagement (e.g. the quick add's suggested title). */
  defaults?: Partial<EngagementFieldValues>;
  /** Overrides the dialog title. */
  heading?: string;
  /** Show only title, channel, date and summary. */
  compact?: boolean;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: EngagementCreateValues, quickLinks: CollectedLink[], tags: string[]) => void;
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
  const [participantIds, setParticipantIds] = useState<string[]>(initialParticipants?.stakeholderIds ?? []);
  const [anonymous, setAnonymous] = useState<AnonymousParticipantEntry[]>(initialParticipants?.anonymous ?? []);
  const offersCreateFields = !initial && !compact && !!projectId;
  const offersParticipants = !compact && !!projectId && (!initial || !!initialParticipants);

  return (
    <Modal title={heading ?? (initial ? `Edit ${initial.title}` : "Log engagement")} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <FormGridFull>
            <TextField helpNotNeeded required label="Title" ariaLabel="Engagement title" value={title} onChange={setTitle} hint="What happened, e.g. “Quarterly review with the regulator”." />
          </FormGridFull>
          <LabeledSelect help={STAKEHOLDERS_HELP.engagementChannel}
            label="Channel" value={channel} placeholder={null}
            onChange={(value) => setChannel(value as EngagementChannel)} options={CHANNEL_OPTIONS}
          />
          <DateField helpNotNeeded required label="Date" value={date} onChange={setDate} />
          {!compact && (
            <FormGridFull>
              <TextAreaField help={STAKEHOLDERS_HELP.engagementPurpose} label="Purpose" rows={2} value={purpose} onChange={setPurpose} />
            </FormGridFull>
          )}
          <FormGridFull>
            <TextAreaField help={STAKEHOLDERS_HELP.engagementSummary} label="Summary" rows={compact ? 3 : 2} value={summary} onChange={setSummary} />
          </FormGridFull>
          {!compact && (
            <>
              <FormGridFull>
                <TextAreaField helpNotNeeded
                  label="Notes" rows={5} value={notes} onChange={setNotes}
                  hint="Notes can name people and are personal data: they are deleted with the engagement."
                />
              </FormGridFull>
              <CheckboxField help={STAKEHOLDERS_HELP.engagementConsent}
                heading="Consent" label="Recorded" ariaLabel="Consent recorded" checked={consent} onChange={setConsent}
              />
              <DateField help={STAKEHOLDERS_HELP.engagementRetainUntil}
                label="Retain until" value={retainUntil} onChange={setRetainUntil}
              />
            </>
          )}
          {offersParticipants && (
            <FormGridFull>
              <div className="stack">
                <ParticipantsField
                  projectId={projectId} value={participantIds} onChange={setParticipantIds}
                  anonymous={anonymous} onAnonymousChange={setAnonymous}
                />
                {offersCreateFields && (
                  <>
                    <QuickLinkField projectId={projectId} artefactType="engagement" preferredType="stakeholder" value={quickLinks} onChange={setQuickLinks} />
                    <TagField projectId={projectId} artefactType="engagement" value={tags} onChange={setTags} />
                  </>
                )}
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
              ...(offersParticipants && (initialParticipants || participantIds.length > 0) ? { stakeholder_ids: participantIds } : {}),
              ...(offersParticipants && (initialParticipants || anonymous.length > 0) ? { anonymous_participants: anonymous } : {}),
            }, quickLinks, tags)}
        saveDisabled={title.trim() === "" || date === ""}
        />
      </div>
    </Modal>
  );
}
