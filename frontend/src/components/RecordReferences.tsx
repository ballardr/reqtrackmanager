/**
 * Module: components/RecordReferences
 *
 * The external references of one existing record, in its header: a chip per reference (the system and the key, a link
 * when the item has one, the role and note on hover) for everyone who can open the record and, for someone who may change
 * them, buttons to add, edit and remove one in place.
 *
 * Responsibilities:
 * - Load the record's references, `can_edit` and the systems to choose from (`RecordReferencesApi`).
 * - Add and edit in a dialog over the shared `ReferenceFields`; remove after a plain confirmation (a key is not always
 *   easy to type again). Every change ends in a toast, and a refusal shows its reason beside the dialog's actions.
 * - Say nothing for a record with no references that the viewer cannot change, when references are switched off for its
 *   type (the server answers 404), or when the read fails: a reference is secondary to the record, so an error is not
 *   shown in its header.
 *
 * `RecordTags` renders it, so every page that shows a record's tags shows its references too (a page that keeps its
 * own references passes `references={false}`). `ReferenceChip` is also used read-only on the compact header line.
 * `api` is injectable.
 */
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import {
  EXTERNAL_REFERENCE_ROLE_LABEL, isWebUrl, recordReferencesApi, referenceLabel, type ExternalReference,
  type RecordReferences as Data, type RecordReferencesApi,
} from "../api/externalReferences";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { FieldCaption, FieldHelp } from "./FieldHelp";
import { referenceInput, type ReferenceDraft } from "./referenceDraft";
import { ReferenceFormModal } from "./ReferenceFormModal";
import { Tooltip } from "./Tooltip";

/**
 * One reference as a chip: `System: key` (the key opens the item in a new tab when it has a web link), the role as a
 * badge, the note as a tooltip. The edit and remove buttons show only when their handlers are given.
 *
 * @param reference The reference.
 * @param onEdit Opens the editor.
 * @param onRemove Asks to remove it.
 */
export function ReferenceChip({
  reference, onEdit, onRemove,
}: { reference: ExternalReference; onEdit?: () => void; onRemove?: () => void }) {
  const strings = useStrings().references;
  const text = reference.key || reference.url || "";
  const href = isWebUrl(reference.link) ? reference.link : null;
  const label = referenceLabel(reference);
  const chip = (
    <span className="chip">
      <span className="chip__label">
        {reference.system_name}:{" "}
        {href ? <a href={href} target="_blank" rel="noopener noreferrer" aria-label={strings.openLink(label)}>{text}</a> : text}
      </span>
      {reference.role && <Badge>{EXTERNAL_REFERENCE_ROLE_LABEL[reference.role]}</Badge>}
      {onEdit && (
        <button type="button" className="chip__remove" title={strings.editLabel(label)} aria-label={strings.editLabel(label)} onClick={onEdit}>
          <Pencil size={12} />
        </button>
      )}
      {onRemove && (
        <button type="button" className="chip__remove" title={strings.removeLabel(label)} aria-label={strings.removeLabel(label)} onClick={onRemove}>
          <Trash2 size={12} />
        </button>
      )}
    </span>
  );
  return reference.note ? <Tooltip label={reference.note}>{chip}</Tooltip> : chip;
}

/**
 * @param projectId The project the page is opened in.
 * @param artefactType The record's registered artefact type.
 * @param artefactId The record's id.
 * @param onChanged Called after a change was saved.
 * @param captioned Shows a visible "External references" caption with its help above the chips (a card in a side panel),
 *   instead of the bare help button that suits the record header's row.
 * @param api The calls (the live ones by default).
 */
export function RecordReferences({
  projectId, artefactType, artefactId, onChanged, captioned = false, api = recordReferencesApi,
}: {
  projectId: string;
  artefactType: string;
  artefactId: string;
  onChanged?: () => void;
  captioned?: boolean;
  api?: RecordReferencesApi;
}) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [data, setData] = useState<Data | null>(null);
  const [editing, setEditing] = useState<ExternalReference | "new" | null>(null);
  const [removing, setRemoving] = useState<ExternalReference | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.get(projectId, artefactType, artefactId)
      .then((result) => active && setData(result))
      .catch(() => active && setData(null));
    return () => {
      active = false;
    };
  }, [api, projectId, artefactType, artefactId]);

  if (!data) return null;
  if (!data.can_edit && data.references.length === 0) return null;
  const text = strings.references;

  async function save(draft: ReferenceDraft) {
    if (editing === null) return;
    setError(null);
    try {
      const body = referenceInput(draft);
      const saved = editing === "new"
        ? await api.add(projectId, artefactType, artefactId, body)
        : await api.update(projectId, artefactType, artefactId, editing.id, body);
      setData(saved);
      showToast(editing === "new" ? text.added : text.updated, "success");
      setEditing(null);
      onChanged?.();
    } catch (err) {
      setError(text.saveFailed(toErrorMessage(err, strings.common.error)));
    }
  }

  async function remove(reference: ExternalReference) {
    setRemoving(null);
    try {
      setData(await api.remove(projectId, artefactType, artefactId, reference.id));
      showToast(text.removed, "success");
      onChanged?.();
    } catch (err) {
      showToast(text.removeFailed(toErrorMessage(err, strings.common.error)), "error");
    }
  }

  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      {captioned && <FieldCaption label={text.label} help={strings.help.recordReferences} />}
      <div className="row" style={{ gap: "var(--space-2)", flexWrap: "wrap", alignItems: "center" }} role="group" aria-label={text.label}>
        {!captioned && <FieldHelp label={text.label} help={strings.help.recordReferences} />}
        {data.references.map((reference) => (
          <ReferenceChip
            key={reference.id} reference={reference}
            onEdit={data.can_edit ? () => { setError(null); setEditing(reference); } : undefined}
            onRemove={data.can_edit ? () => setRemoving(reference) : undefined}
          />
        ))}
        {data.can_edit && data.systems.length > 0 && (
          <Tooltip label={text.addLabel}>
            <button
              type="button" className="btn btn-sm btn-icon" aria-label={text.addLabel} aria-haspopup="dialog"
              onClick={() => { setError(null); setEditing("new"); }}
            >
              <Plus size={14} aria-hidden="true" />
            </button>
          </Tooltip>
        )}
      </div>
      {editing !== null && (
        <ReferenceFormModal
          initial={editing === "new" ? undefined : editing} systems={data.systems} error={error}
          onCancel={() => setEditing(null)} onSave={save}
        />
      )}
      {removing && (
        <ConfirmDialog
          title={text.removeTitle} message={text.removeMessage(referenceLabel(removing))} confirmLabel={text.removeConfirm}
          onConfirm={() => remove(removing)} onCancel={() => setRemoving(null)}
        />
      )}
    </div>
  );
}
