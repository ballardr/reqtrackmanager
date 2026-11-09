/**
 * Module: components/AnnouncementEditor
 *
 * The create/edit dialog for an announcement: title, message, severity, the window it is shown in, whether the
 * login pages show it and whether a person can dismiss it. Used by `AnnouncementsPanel` for both the platform and an organisation, so the two cannot
 * drift. The window is entered in the person's local time and sent as UTC instants (`utils/dateTimeLocal`). A new
 * message starts now and has no end; Duplicate opens the dialog with another message's content and the same defaults.
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
 * @param duplicateOf A message whose content prefills a new one (its window and notification are not copied); ignored when editing.
 * @param organisationScope True for an organisation's message, which may not contain a web address (said in the field hint).
 * @param error A save error to show.
 * @param onCancel Called when the dialog is dismissed.
 * @param onSave Called with the fields, the window as UTC instants.
 */
export function AnnouncementEditor({
  announcement, duplicateOf, organisationScope, error, onCancel, onSave,
}: {
  announcement: Announcement | null;
  duplicateOf?: Announcement | null;
  organisationScope: boolean;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: AnnouncementWrite) => void;
}) {
  const strings = useStrings();
  const text = strings.announcements;
  const source = announcement ?? duplicateOf ?? null;
  const [title, setTitle] = useState(source?.title ?? "");
  const [body, setBody] = useState(source?.body ?? "");
  const [severity, setSeverity] = useState<AnnouncementSeverity>(source?.severity ?? "information");
  // A new message starts now (the person's local time, stored as a UTC instant) and has no end.
  const [startsAt, setStartsAt] = useState(() => isoToLocalInput(announcement ? announcement.starts_at : new Date().toISOString()));
  const [endsAt, setEndsAt] = useState(isoToLocalInput(announcement?.ends_at ?? null));
  const [showOnLogin, setShowOnLogin] = useState(source?.show_on_login ?? false);
  const [dismissible, setDismissible] = useState(source?.dismissible ?? true);
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
          <TextField label={text.endsAt} help={strings.help.announcementEnd} value={endsAt} onChange={setEndsAt} inputProps={{ type: "datetime-local" }} />
        </div>
        {windowInvalid && <div style={{ color: "var(--color-danger)" }}>{text.endBeforeStart}</div>}
        <CheckboxField label={text.showOnLogin} help={strings.help.announcementLogin} checked={showOnLogin} onChange={setShowOnLogin} />
        <CheckboxField label={text.dismissible} help={strings.help.announcementDismissible} checked={dismissible} onChange={setDismissible} />
        <FormActions
          error={error} onCancel={onCancel} saveDisabled={title.trim() === "" || windowInvalid}
          onSave={() => onSave({
            title: title.trim(), body: body.trim(), severity, starts_at: startIso, ends_at: endIso, show_on_login: showOnLogin, dismissible,
          })}
        />
      </div>
    </Modal>
  );
}
