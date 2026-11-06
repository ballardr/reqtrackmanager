/**
 * Module: components/CreateLinkedRecord
 *
 * The "Create new record" choice of the shared Links panel's "Add link" menu: creates a record of another type and
 * links it to the page's record in one step, so a person does not leave the page to make the thing they want to link to.
 *
 * Responsibilities:
 * - `useCreatableRecordTypes` (`hooks/useCreatableRecordTypes`): offer each record type a link type from the page's record reaches (the server's link
 *   options, already filtered by restriction, enabled modules and what the caller may link) that the owning module
 *   can create (`modules/linkedRecordCreators`) and that the server says the caller may create (`can_create`); an empty list means the panel offers no create choice, so a record never offers one that would be refused.
 * - `CreateLinkedRecordDialog`: step 1 chooses the record type and the relationship; step 2 shows the owning module's
 *   own create dialog (core never imports a module's form) and links the new record once it reports the id.
 *
 * Design decisions:
 * - The relationship defaults to the one the page record's module prefers (`preferredLinkPhrases`: a request's
 *   Pain Points are the ones it "Addresses", which other features count), else the first specific link type; the
 *   symmetric "Related to" leads only when nothing else reaches the type. Changing the record type resets the
 *   relationship to that type's default.
 * - The default relationship is the first option and is marked "(default)" when there is a choice.
 * - With one creatable type the record type select is unavailable and a tooltip (beside the pointer) says why, so a person does not
 *   wonder whether something is missing.
 * - The two choices are a step of their own, in a modal, so the panel header keeps one "Add link" control (a menu of
 *   linking an existing record or creating a new one) and its Trace and View options buttons stay on the same row.
 * - Not offered while links need a change request (the panel does not ask then): the new record would have to be
 *   proposed, not linked.
 */
import { useState } from "react";

import type { ArtefactLinksApi } from "../api/artefactLinks";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import type { CreatableRecordType } from "../hooks/useCreatableRecordTypes";
import { getLinkedRecordCreator } from "../modules/linkedRecordCreators";
import { FormActions } from "./FormActions";
import { LabeledSelect } from "./LabeledSelect";
import { optionKey } from "./linkOptions";
import { Modal } from "./Modal";
import { Tooltip } from "./Tooltip";

/**
 * Step 1 (record type and relationship) and step 2 (the owning module's create dialog) of creating and linking a record.
 *
 * @param projectId The project of the page's record.
 * @param artefactType The page record's registered artefact type.
 * @param artefactId The page record's id.
 * @param types The creatable types (`useCreatableRecordTypes`); at least one.
 * @param api The links API (injectable for stories and tests).
 * @param onLinked Called after a new record is created (linked or not), so the panel reloads.
 * @param onClose Called when the person leaves without creating anything, and after step 2 finishes.
 */
export function CreateLinkedRecordDialog({
  projectId, artefactType, artefactId, types, api, onLinked, onClose,
}: {
  projectId: string;
  artefactType: string;
  artefactId: string;
  types: CreatableRecordType[];
  api: ArtefactLinksApi;
  onLinked: () => void;
  onClose: () => void;
}) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [typeKey, setTypeKey] = useState(types[0].type);
  // The relationship chosen for the current type; "" uses the type's default (its first, most specific, one).
  const [relationshipKey, setRelationshipKey] = useState("");
  const [step, setStep] = useState<1 | 2>(1);

  const entry = types.find((t) => t.type === typeKey) ?? types[0];
  const option = entry.options.find((o) => optionKey(o) === relationshipKey) ?? entry.options[0];

  async function created(id: string) {
    onClose();
    try {
      await api.create(projectId, artefactType, artefactId, {
        link_type_id: option.link_type_id, direction: option.direction, other_type: entry.type, other_id: id,
      });
      showToast(strings.artefactLinks.createdAndLinked(entry.label));
    } catch (err) {
      showToast(`${strings.artefactLinks.createdNotLinked(entry.label)} ${toErrorMessage(err, "")}`.trim(), "error");
    }
    onLinked();
  }

  if (step === 2) {
    return getLinkedRecordCreator(entry.type)?.render({
      projectId, onCreated: (id) => void created(id), onCancel: onClose,
    }) ?? null;
  }
  const typeSelect = (
    <LabeledSelect helpNotNeeded
      label={strings.artefactLinks.createNewTypeLabel} value={typeKey} placeholder={null}
      disabled={types.length === 1}
      onChange={(value) => { setTypeKey(value); setRelationshipKey(""); }}
      options={types.map((t) => ({ value: t.type, label: t.label }))}
    />
  );
  return (
    <Modal title={strings.artefactLinks.createStepTitle} onClose={onClose}>
      <div className="stack">
        {/* With one choice the select is unavailable and says why on hover; a disabled control takes no hover itself, so the tooltip wraps it. */}
        {types.length === 1 ? (
          <Tooltip label={strings.artefactLinks.createSingleType(entry.label)} wrap followPointer style={{ display: "block" }}>{typeSelect}</Tooltip>
        ) : typeSelect}
        <LabeledSelect helpNotNeeded
          label={strings.artefactLinks.linkTypeLabel} value={optionKey(option)} placeholder={null}
          onChange={setRelationshipKey}
          options={entry.options.map((o, i) => ({
            value: optionKey(o), label: i === 0 && entry.options.length > 1 ? strings.artefactLinks.createDefaultRelationship(o.phrase) : o.phrase,
          }))}
        />
        <FormActions onCancel={onClose} onSave={() => setStep(2)} saveLabel={strings.artefactLinks.createNext} />
      </div>
    </Modal>
  );
}
