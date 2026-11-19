/**
 * Module: components/ReferenceField
 *
 * The "External references" field of a create form: add the references the new record starts with. Nothing is written
 * here; the choice is held for `useCommitTags`, which adds them once the record exists, the same contract as
 * `TagField`, `ComponentField` and `QuickLinkField` (`hooks/pendingReferences`).
 *
 * It asks the server about a record that does not exist yet (`DRAFT_ARTEFACT_ID`), so the caller's authority is the one
 * that will apply, and it renders nothing when the caller may not change references of this kind of record, references
 * are switched off for it, the project has no system to choose, or the read fails: a form never offers a field that
 * would be refused. `TagField` renders it, so every create form that has tags has this too. It is made of the shared
 * `ReferenceFields`, the same group the record page's editor uses.
 */
import { Plus, X } from "lucide-react";
import { useEffect, useState } from "react";

import { DRAFT_ARTEFACT_ID } from "../api/artefactLinks";
import { recordReferencesApi, type RecordReferencesApi, type ReferenceSystem } from "../api/externalReferences";
import { useStrings } from "../context/TerminologyContext";
import { setPendingReferences } from "../hooks/pendingReferences";
import { FieldCaption } from "./FieldHelp";
import { BLANK_REFERENCE, referenceInputs, type ReferenceDraft } from "./referenceDraft";
import { ReferenceFields } from "./ReferenceFields";

/**
 * @param projectId The project the record is being created in.
 * @param artefactType The registered type of the record being created.
 * @param api Injectable calls (stories pass a fake).
 */
export function ReferenceField({
  projectId, artefactType, api = recordReferencesApi,
}: { projectId: string; artefactType: string; api?: RecordReferencesApi }) {
  const strings = useStrings();
  const [systems, setSystems] = useState<ReferenceSystem[] | null>(null);
  const [drafts, setDrafts] = useState<ReferenceDraft[]>([]);

  useEffect(() => {
    let active = true;
    api.get(projectId, artefactType, DRAFT_ARTEFACT_ID)
      .then((draft) => active && setSystems(draft.can_edit ? draft.systems : null))
      .catch(() => active && setSystems(null));
    return () => {
      active = false;
    };
  }, [api, projectId, artefactType]);

  // A form that closes (saved or cancelled) leaves nothing behind for the next create of this type.
  useEffect(() => () => setPendingReferences(projectId, artefactType, []), [projectId, artefactType]);

  if (!systems || systems.length === 0) return null;
  const change = (next: ReferenceDraft[]) => {
    setDrafts(next);
    setPendingReferences(projectId, artefactType, referenceInputs(next));
  };
  return (
    <section className="stack" aria-label={strings.references.label}>
      <FieldCaption label={strings.references.label} help={strings.help.recordReferences} />
      {drafts.map((draft, index) => (
        <div key={index} style={{ display: "flex", gap: "var(--space-2)", alignItems: "flex-start" }}>
          <div className="form-grid" style={{ "--form-grid-min": "10rem", flex: 1 } as React.CSSProperties}>
            <ReferenceFields
              draft={draft} systems={systems} ordinal={index + 1}
              onChange={(next) => change(drafts.map((d, i) => (i === index ? next : d)))}
            />
          </div>
          {/* Level with the inputs, below their captions. */}
          <button
            type="button" className="btn btn-sm btn-icon btn-danger" style={{ marginTop: "1.65rem" }}
            title={strings.references.removeRowLabel(index + 1)} aria-label={strings.references.removeRowLabel(index + 1)}
            onClick={() => change(drafts.filter((_, i) => i !== index))}
          >
            <X />
          </button>
        </div>
      ))}
      <div>
        <button type="button" className="btn btn-sm" onClick={() => change([...drafts, BLANK_REFERENCE])}>
          <Plus size={14} aria-hidden="true" /> {strings.references.addRow}
        </button>
      </div>
    </section>
  );
}
