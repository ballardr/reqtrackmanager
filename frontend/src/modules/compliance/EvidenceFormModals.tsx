/**
 * Module: modules/compliance/EvidenceFormModals
 *
 * The evidence dialogs shared by the Evidence list (add), the evidence detail page (edit, revalidate)
 * and the requirement assessment panel (add and link): `EvidenceFormModal` and `RevalidateModal`.
 * Both are plain `Modal` forms that hand their values to the caller; neither calls the API itself.
 */
import { Paperclip } from "lucide-react";
import { useState } from "react";

import { DateField, TextAreaField, TextField } from "../../components/FormFields";
import { FormActions } from "../../components/FormActions";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { FileUploadTrigger } from "../../components/FileUploadTrigger";
import { Modal } from "../../components/Modal";
import { RemovableChip } from "../../components/RemovableChip";
import type { ComplianceEvidence } from "./types";

/**
 * Add / edit form for one piece of evidence. Create mode also stages files to upload once the record exists.
 *
 * @param initial The evidence being edited; omit to create.
 * @param onCancel Called when the dialog is dismissed.
 * @param onSave Called with the field values and any files staged at creation.
 */
export function EvidenceFormModal({
  initial,
  onCancel,
  onSave,
}: {
  initial?: ComplianceEvidence;
  onCancel: () => void;
  onSave: (
    values: {
      title: string; description: string; issuing_organisation: string | null; issued_date: string | null;
      expiry_date?: string | null; notes: string;
    },
    files: File[]
  ) => void;
}) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [issuingOrganisation, setIssuingOrganisation] = useState(initial?.issuing_organisation ?? "");
  const [issuedDate, setIssuedDate] = useState(initial?.issued_date ?? "");
  const [expiryDate, setExpiryDate] = useState(initial?.expiry_date ?? "");
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [stagedFiles, setStagedFiles] = useState<File[]>([]);

  return (
    <Modal title={initial ? "Edit evidence" : "Add evidence"} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <FormGridFull>
            <TextField helpNotNeeded required label="Title" ariaLabel="Evidence title" value={title} onChange={setTitle} />
          </FormGridFull>
          <FormGridFull>
            <TextAreaField helpNotNeeded label="Description" value={description} onChange={setDescription} rows={2} />
          </FormGridFull>
          <TextField helpNotNeeded label="Issuing organisation" value={issuingOrganisation} onChange={setIssuingOrganisation} />
          <DateField helpNotNeeded label="Issued date" value={issuedDate} onChange={setIssuedDate} />
          {!initial && (
            <DateField helpNotNeeded
              label="Expiry date"
              hint="Change it later with Revalidate."
              value={expiryDate}
              onChange={setExpiryDate}
            />
          )}
          <FormGridFull>
            <TextAreaField helpNotNeeded label="Notes" value={notes} onChange={setNotes} rows={2} />
          </FormGridFull>
          {!initial && (
            <FormGridFull>
              <div className="stack" style={{ gap: "0.25rem" }}>
                <span>Files</span>
                {stagedFiles.length > 0 && (
                  <div className="row" style={{ flexWrap: "wrap" }}>
                    {stagedFiles.map((file, index) => (
                      <RemovableChip
                        key={`${file.name}-${index}`}
                        label={file.name}
                        removeLabel={`Remove ${file.name}`}
                        onRemove={() => setStagedFiles((prev) => prev.filter((_, i) => i !== index))}
                      />
                    ))}
                  </div>
                )}
                <FileUploadTrigger
                  onSelect={(file) => setStagedFiles((prev) => [...prev, file])}
                  title="Attach a file"
                  aria-label="Attach a file"
                >
                  <Paperclip size={14} /> Attach a file
                </FileUploadTrigger>
              </div>
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions
          onCancel={onCancel}
          onSave={() =>
            onSave(
              {
                title, description, issuing_organisation: issuingOrganisation || null,
                issued_date: issuedDate || null, expiry_date: initial ? undefined : (expiryDate || null), notes,
              },
              stagedFiles
            )}
          saveDisabled={!title.trim()}
        />
      </div>
    </Modal>
  );
}

/**
 * Revalidate dialog: records a new expiry date and the justification (appended to the revalidation history).
 *
 * @param onCancel Called when the dialog is dismissed.
 * @param onSave Called with the new expiry date (or null for none) and the justification.
 */
export function RevalidateModal({
  onCancel,
  onSave,
}: {
  onCancel: () => void;
  onSave: (values: { new_expiry_date: string | null; justification: string }) => void;
}) {
  const [newExpiryDate, setNewExpiryDate] = useState("");
  const [justification, setJustification] = useState("");

  return (
    <Modal title="Revalidate evidence" onClose={onCancel}>
      <div className="stack">
        <FormGrid minColumn="18rem">
          <DateField helpNotNeeded label="New expiry date" value={newExpiryDate} onChange={setNewExpiryDate} />
          <FormGridFull>
            <TextAreaField helpNotNeeded label="Justification" value={justification} onChange={setJustification} rows={2} />
          </FormGridFull>
        </FormGrid>
        <FormActions
          onCancel={onCancel}
          onSave={() => onSave({ new_expiry_date: newExpiryDate || null, justification })}
          saveLabel="Revalidate"
        />
      </div>
    </Modal>
  );
}
