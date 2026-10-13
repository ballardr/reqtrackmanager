/**
 * Module: modules/stakeholders/EngagementFormModal
 *
 * Create/edit dialog for an Engagement's content fields (docs/ux-style-guide.md
 * principle 3: a full entity create/edit is a `Modal`). Shared by create, edit
 * (distinguished by whether `initial` is passed) and the "Log contact" quick
 * add. `compact` keeps only title, channel, date and summary for the quick add;
 * the rest (purpose, notes, consent, retain-until) is filled in from the detail
 * page. The facilitator and the people involved are assigned from the detail
 * page, so the form never needs a picker. Channel renders through its label
 * map and every control has a visible label (principle 13).
 */
import { useState } from "react";

import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { CheckboxField, DateField, TextAreaField, TextField } from "./RecordFormFields";
import type { Engagement, EngagementChannel, EngagementFieldValues } from "./types";
import { ENGAGEMENT_CHANNEL_LABEL } from "./types";

const CHANNEL_OPTIONS = Object.entries(ENGAGEMENT_CHANNEL_LABEL).map(([value, label]) => ({ value, label }));

/** Today as YYYY-MM-DD in the viewer's timezone (the engagement date defaults to the day it is logged). */
function today(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

export function EngagementFormModal({
  initial,
  defaults,
  heading,
  compact = false,
  error,
  onCancel,
  onSave,
}: {
  initial?: Engagement;
  /** Starting values for a new engagement (e.g. the quick add's suggested title). */
  defaults?: Partial<EngagementFieldValues>;
  /** Overrides the dialog title. */
  heading?: string;
  /** Show only title, channel, date and summary. */
  compact?: boolean;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: EngagementFieldValues) => void;
}) {
  const seed = initial ?? defaults;
  const [title, setTitle] = useState(seed?.title ?? "");
  const [channel, setChannel] = useState<EngagementChannel>(seed?.channel ?? "meeting");
  const [date, setDate] = useState(seed?.engagement_date ?? today());
  const [purpose, setPurpose] = useState(seed?.purpose ?? "");
  const [summary, setSummary] = useState(seed?.summary ?? "");
  const [notes, setNotes] = useState(seed?.notes ?? "");
  const [consent, setConsent] = useState(seed?.consent_recorded ?? false);
  const [retainUntil, setRetainUntil] = useState(seed?.retain_until ?? "");

  return (
    <Modal title={heading ?? (initial ? `Edit ${initial.title}` : "Log engagement")} onClose={onCancel} size="lg">
      <div className="stack">
        <TextField label="Title" ariaLabel="Engagement title" value={title} onChange={setTitle} hint="What happened, e.g. “Quarterly review with the regulator”." />
        <LabeledSelect
          label="Channel" value={channel} placeholder={null}
          onChange={(value) => setChannel(value as EngagementChannel)} options={CHANNEL_OPTIONS}
        />
        <DateField label="Date" value={date} onChange={setDate} />
        {!compact && <TextAreaField label="Purpose" rows={2} value={purpose} onChange={setPurpose} hint="Why the engagement took place." />}
        <TextAreaField label="Summary" rows={compact ? 3 : 2} value={summary} onChange={setSummary} hint="A line or two on the outcome." />
        {!compact && (
          <>
            <TextAreaField
              label="Notes" rows={5} value={notes} onChange={setNotes}
              hint="Notes can name people and are personal data: they are deleted with the engagement."
            />
            <CheckboxField label="Consent recorded" checked={consent} onChange={setConsent} hint="Tick once the participants have agreed to being recorded here." />
            <DateField
              label="Retain until" value={retainUntil} onChange={setRetainUntil}
              hint="Optional. Nothing is deleted automatically; the engagement is flagged when this date is reached."
            />
          </>
        )}
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button
            className="btn btn-primary"
            disabled={title.trim() === "" || date === ""}
            onClick={() =>
              onSave({
                title: title.trim(), channel, engagement_date: date, purpose, summary, notes,
                consent_recorded: consent, retain_until: retainUntil === "" ? null : retainUntil,
              })
            }
          >
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}
