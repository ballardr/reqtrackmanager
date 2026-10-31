/**
 * Module: components/ReportLayoutFormModal
 *
 * The create and edit dialog of a report layout: its name, description and folder (both modes, through the one
 * `ReportLayoutFields` group), its own branding template (editing only: it is set when modifying a layout, and the
 * organisation's default applies until then) and, when creating, the kind of report (document or table), which
 * cannot change afterwards. Creating starts the layout empty; the designer is where its content is written.
 *
 * Responsibilities: validate the name locally, call the API, show the server's refusal (a taken name) in the
 * dialog's header. The caller owns the toast, the reload and any navigation, through `onSaved`.
 */
import { useMemo, useState } from "react";

import type { LayoutFamily, ReportLayoutApi, ReportLayoutDetail, ReportLayoutSummary } from "../api/reportLayouts";
import { LAYOUT_FAMILY_LABEL } from "../api/reportLayouts";
import { reportFolderApi, type ReportFolderApi } from "../api/reportFolders";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { tidyFolder } from "../utils/reportFolders";
import { FormActions } from "./FormActions";
import { TextAreaField, TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { ReportFolderField } from "./ReportFolderField";

/** The fields a layout's create and edit forms share, so a field added later reaches both. */
export function ReportLayoutFields({
  name, description, folder, folderApi, onName, onDescription, onFolder, onFoldersChanged, onFolderBusy,
}: {
  name: string; description: string; folder: string; folderApi: ReportFolderApi; onFoldersChanged?: () => void;
  /** Told while a folder change is in flight (the form keeps Save disabled). */
  onFolderBusy?: (busy: boolean) => void;
  onName: (value: string) => void; onDescription: (value: string) => void; onFolder: (value: string) => void;
}) {
  const strings = useStrings().reportLayouts;
  return (
    <>
      <TextField helpNotNeeded required
        label={strings.nameLabel} value={name} onChange={onName} inputProps={{ maxLength: 200, autoFocus: true }}
      />
      <TextAreaField helpNotNeeded label={strings.descriptionLabel} value={description} onChange={onDescription} />
      <ReportFolderField value={folder} onChange={onFolder} api={folderApi} onChanged={onFoldersChanged} onBusyChange={onFolderBusy} />
    </>
  );
}

/**
 * @param api The calls bound to the scope the layout belongs to.
 * @param layout The layout to edit; omit it to create one.
 * @param onClose Called by Cancel and after a save.
 * @param onSaved Called with the saved layout after a create or edit (before `onClose`).
 */
export function ReportLayoutFormModal({
  api, layout, onClose, onSaved, folderApi: folderApiProp, onFoldersChanged,
}: {
  api: ReportLayoutApi;
  /** The folder calls for the layout's scope; the live ones for `api.scope` when omitted. */
  folderApi?: ReportFolderApi;
  /** Called after a folder is added, renamed or deleted, so the page behind can reload. */
  onFoldersChanged?: () => void;
  layout?: ReportLayoutSummary;
  onClose: () => void;
  onSaved: (saved: ReportLayoutSummary, created: boolean) => void;
}) {
  const strings = useStrings();
  const text = strings.reportLayouts;
  const [name, setName] = useState(layout?.name ?? "");
  const [description, setDescription] = useState(layout?.description ?? "");
  const [folder, setFolder] = useState(layout?.folder ?? "");
  const folderApi = useMemo(() => folderApiProp ?? reportFolderApi(api.scope), [folderApiProp, api.scope]);
  const [family, setFamily] = useState<LayoutFamily>(layout?.family ?? "document");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [folderBusy, setFolderBusy] = useState(false);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      let saved: ReportLayoutSummary | ReportLayoutDetail;
      if (layout) {
        saved = await api.update(layout.id, {
          name: name.trim(), description, folder: tidyFolder(folder),
        });
      } else {
        // The server writes the empty tree of a family, so the client never spells out the tree's shape.
        const parsed = await api.parseText(`@layout ${family}\n`);
        if (!parsed.tree) throw new Error(strings.common.error);
        saved = await api.create({ name: name.trim(), description, folder: tidyFolder(folder), family, tree: parsed.tree });
      }
      onSaved(saved, !layout);
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={layout ? text.editTitle : text.createTitle} onClose={onClose}>
      <div className="stack">
        <ReportLayoutFields
          name={name} description={description} folder={folder} folderApi={folderApi} onFoldersChanged={onFoldersChanged} onFolderBusy={setFolderBusy}
          onName={setName} onDescription={setDescription} onFolder={setFolder}
        />
        {!layout && (
          <LabeledSelect required
            label={text.familyLabel}
            help={strings.help.reportLayoutFamily}
            value={family}
            onChange={(next) => setFamily(next as LayoutFamily)}
            options={(Object.keys(LAYOUT_FAMILY_LABEL) as LayoutFamily[]).map((key) => ({ value: key, label: LAYOUT_FAMILY_LABEL[key] }))}
            placeholder={null}
          />
        )}
        <FormActions
          error={error}
          onCancel={onClose}
          onSave={() => void save()}
          saveLabel={layout ? strings.common.save : text.createButton}
          saveDisabled={busy || folderBusy || name.trim() === ""}
          cancelDisabled={busy}
        />
      </div>
    </Modal>
  );
}
