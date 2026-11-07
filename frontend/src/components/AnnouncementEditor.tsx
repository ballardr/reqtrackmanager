/**
 * Module: components/AnnouncementEditor
 *
 * The create/edit dialog for an announcement: title, message, severity, the window it is shown in and whether the
 * login pages show it. Used by `AnnouncementsPanel` for both the platform and an organisation, so the two cannot
 * drift. The window is entered in the person's local time and sent as UTC instants (`utils/dateTimeLocal`).
 *
 * The caller saves. Validation here only covers what is certain in the browser (a title, an end after the start);
 * the server's own rules (text, a web address in an organisation message) come back as the error shown above the form.
 */
import { useState } from "react";

import type { Announcement, AnnouncementSeverity, AnnouncementWrite } from "../api/types";
import { ANNOUNCEMENT_SEVERITIES, ANNOUNCEMENT_SEVERITY_LABEL } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { isoToLocalInput, localInputToIso } from "../utils/dateTimeLocal";
import { FormActions } from "./FormActions";
import { CheckboxField, TextAreaField, TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";

/** The longest message the server accepts. */
const MAX_BODY_LENGTH = 1000;
/** The longest title the server accepts. */
const MAX_TITLE_LENGTH = 120;

/**
 * @param announcement The message being edited, or null to create one.
 * @param organisationScope True for an organisation's message, which may not contain a web address (said in the field hint).
 * @param error A save error to show.
 * @param onCancel Called when the dialog is dismissed.
 * @param onSave Called with the fields, the window as UTC instants.
 */
export function AnnouncementEditor({
  announcement, organisationScope, error, onCancel, onSave,
}: {
  announcement: Announcement | null;
  organisationScope: boolean;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: AnnouncementWrite) => void;
}) {
  const strings = useStrings();
  const text = strings.announcements;
  const [title, setTitle] = useState(announcement?.title ?? "");
  const [body, setBody] = useState(announcement?.body ?? "");
  const [severity, setSeverity] = useState<AnnouncementSeverity>(announcement?.severity ?? "information");
  const [startsAt, setStartsAt] = useState(isoToLocalInput(announcement?.starts_at ?? null));
  const [endsAt, setEndsAt] = useState(isoToLocalInput(announcement?.ends_at ?? null));
  const [showOnLogin, setShowOnLogin] = useState(announcement?.show_on_login ?? false);
  const startIso = localInputToIso(startsAt);
  const endIso = localInputToIso(endsAt);
  const windowInvalid = startIso !== null && endIso !== null && endIso <= startIso;
  return (
    <Modal title={announcement ? text.editMessage : text.newMessage} onClose={onCancel} size="lg">
      <div className="stack">
        <TextField
          helpNotNeeded required label={text.title} value={title} onChange={setTitle}
          inputProps={{ maxLength: MAX_TITLE_LENGTH, autoFocus: true }}
        />
        <TextAreaField
          helpNotNeeded label={text.body} value={body} onChange={setBody} rows={3}
          hint={organisationScope ? text.organisationBodyHint : text.bodyHint} inputProps={{ maxLength: MAX_BODY_LENGTH }}
        />
        <LabeledSelect
          required label={text.severity} help={strings.help.announcementSeverity} value={severity} placeholder={null}
          onChange={(next) => setSeverity(next as AnnouncementSeverity)}
          options={ANNOUNCEMENT_SEVERITIES.map((value) => ({ value, label: ANNOUNCEMENT_SEVERITY_LABEL[value] }))}
        />
        <div className="row" style={{ alignItems: "flex-start" }}>
          <TextField label={text.startsAt} help={strings.help.announcementWindow} value={startsAt} onChange={setStartsAt} inputProps={{ type: "datetime-local" }} />
          <TextField helpNotNeeded label={text.endsAt} value={endsAt} onChange={setEndsAt} inputProps={{ type: "datetime-local" }} />
        </div>
        {windowInvalid && <div style={{ color: "var(--color-danger)" }}>{text.endBeforeStart}</div>}
        <CheckboxField label={text.showOnLogin} help={strings.help.announcementLogin} checked={showOnLogin} onChange={setShowOnLogin} />
        <FormActions
          error={error} onCancel={onCancel} saveDisabled={title.trim() === "" || windowInvalid}
          onSave={() => onSave({
            title: title.trim(), body: body.trim(), severity, starts_at: startIso, ends_at: endIso, show_on_login: showOnLogin,
          })}
        />
      </div>
    </Modal>
  );
}
