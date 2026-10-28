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
import { useState } from "react";

import type { LayoutFamily, ReportLayoutApi, ReportLayoutDetail, ReportLayoutSummary } from "../api/reportLayouts";
import { LAYOUT_FAMILY_LABEL } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { useFolderSuggestions } from "../hooks/useFolderSuggestions";
import { useReportTemplates } from "../hooks/useReportTemplates";
import type { ReportTemplate } from "../api/types";
import { folderProblem, tidyFolder } from "../utils/reportFolders";
import { FormActions } from "./FormActions";
import { TextAreaField, TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { ReportFolderField } from "./ReportFolderField";
import { Modal } from "./Modal";

/** The fields a layout's create and edit forms share, so a field added later reaches both. */
export function ReportLayoutFields({
  name, description, folder, folders, onName, onDescription, onFolder, templates, templateId, onTemplate,
}: {
  name: string; description: string; folder: string; folders: string[];
  onName: (value: string) => void; onDescription: (value: string) => void; onFolder: (value: string) => void;
  /** The organisation's templates, offered only when there are any (editing). */
  templates?: ReportTemplate[]; templateId?: string; onTemplate?: (value: string) => void;
}) {
  const allStrings = useStrings();
  const strings = allStrings.reportLayouts;
  return (
    <>
      <TextField helpNotNeeded required
        label={strings.nameLabel} value={name} onChange={onName} inputProps={{ maxLength: 200, autoFocus: true }}
      />
      <TextAreaField helpNotNeeded label={strings.descriptionLabel} value={description} onChange={onDescription} />
      <ReportFolderField value={folder} onChange={onFolder} suggestions={folders} />
      {templates && templates.length > 0 && onTemplate && (
        <LabeledSelect
          label={strings.templateLabel} help={allStrings.help.reportLayoutTemplate}
          value={templateId ?? ""} onChange={onTemplate}
          options={templates.map((t) => ({ value: t.id, label: t.name }))}
          placeholder={strings.templateDefault}
        />
      )}
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
  api, layout, onClose, onSaved,
}: {
  api: ReportLayoutApi;
  layout?: ReportLayoutSummary;
  onClose: () => void;
  onSaved: (saved: ReportLayoutSummary, created: boolean) => void;
}) {
  const strings = useStrings();
  const text = strings.reportLayouts;
  const [name, setName] = useState(layout?.name ?? "");
  const [description, setDescription] = useState(layout?.description ?? "");
  const [folder, setFolder] = useState(layout?.folder ?? "");
  const [templateId, setTemplateId] = useState(layout?.report_template_id ?? "");
  const templates = useReportTemplates(layout?.organization_id);
  const folders = useFolderSuggestions(api.list);
  const [family, setFamily] = useState<LayoutFamily>(layout?.family ?? "document");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      let saved: ReportLayoutSummary | ReportLayoutDetail;
      if (layout) {
        saved = await api.update(layout.id, {
          name: name.trim(), description, folder: tidyFolder(folder), report_template_id: templateId || null,
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
          name={name} description={description} folder={folder} folders={folders}
          onName={setName} onDescription={setDescription} onFolder={setFolder}
          templates={layout ? templates : undefined} templateId={templateId} onTemplate={setTemplateId}
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
          saveDisabled={busy || name.trim() === "" || folderProblem(folder) !== null}
          cancelDisabled={busy}
        />
      </div>
    </Modal>
  );
}
