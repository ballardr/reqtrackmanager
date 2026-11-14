/**
 * Module: modules/architecture/StateFormModal
 *
 * Create and edit dialog for a state of a state machine diagram, shared by the editor's palette (create, as a state is
 * dropped or added) and the Selection card (edit), told apart by whether `initial` is passed. A marker (initial state, final
 * state, choice) takes only a name: it is a shape with no inside. A new state also takes quick links and tags, as every
 * create form of a linkable, taggable type does; Cancel on a new state creates nothing.
 */
import { useState } from "react";

import type { CollectedLink } from "../../api/artefactLinks";
import { FormActions } from "../../components/FormActions";
import { TextAreaField, TextField } from "../../components/FormFields";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { labelOptions } from "../../utils/labelOptions";
import { ARCHITECTURE_HELP } from "./help";
import { blankStateValues, valuesFromState } from "./stateFields";
import { isMarkerKind } from "./stateMachineModel";
import { STATE_KIND_LABEL, type ArchitectureState, type StateFieldValues, type StateKind } from "./types";

/** What a new state takes beyond the shared fields. */
export interface StateCreateExtras {
  quickLinks: CollectedLink[];
  tags: string[];
}

/**
 * @param projectId The diagram's project, for quick links and tags.
 * @param initial The state being edited; omit to create.
 * @param defaultKind The kind a new state starts as (the palette item chosen).
 * @param holdsStates True when the state being edited has child states, which a marker cannot have (the kind is then fixed).
 * @param error A save error to show.
 * @param onSave Called with the values and, for a new state, the extras.
 */
export function StateFormModal({
  projectId, initial, defaultKind = "state", holdsStates = false, error, onCancel, onSave,
}: {
  projectId: string;
  initial?: ArchitectureState;
  defaultKind?: StateKind;
  holdsStates?: boolean;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: StateFieldValues, extras: StateCreateExtras) => void;
}) {
  const [values, setValues] = useState<StateFieldValues>(() => (initial ? valuesFromState(initial) : blankStateValues(defaultKind)));
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const set = <K extends keyof StateFieldValues>(key: K, value: StateFieldValues[K]) => setValues((prev) => ({ ...prev, [key]: value }));
  const marker = isMarkerKind(values.kind);
  const valid = values.name.trim() !== "";
  const kinds = labelOptions(STATE_KIND_LABEL).filter((o) => !holdsStates || !isMarkerKind(o.value));

  return (
    <Modal title={initial ? `Edit ${initial.name}` : `New ${STATE_KIND_LABEL[values.kind].toLowerCase()}`} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <FormGridFull>
            <TextField helpNotNeeded required label="Name" value={values.name} onChange={(value) => set("name", value)} />
          </FormGridFull>
          <LabeledSelect
            help={ARCHITECTURE_HELP.stateKind} label="Kind" value={values.kind} placeholder={null} options={kinds}
            onChange={(next) => set("kind", next as StateKind)}
          />
          {!marker && (
            <>
              <FormGridFull>
                <TextAreaField helpNotNeeded label="Description" value={values.description} onChange={(value) => set("description", value)} />
              </FormGridFull>
              <TextField help={ARCHITECTURE_HELP.stateEntry} label="Entry action" value={values.entry_action} onChange={(value) => set("entry_action", value)} />
              <TextField help={ARCHITECTURE_HELP.stateExit} label="Exit action" value={values.exit_action} onChange={(value) => set("exit_action", value)} />
              <FormGridFull>
                <TextField help={ARCHITECTURE_HELP.stateActivity} label="Activity" value={values.activity} onChange={(value) => set("activity", value)} />
              </FormGridFull>
            </>
          )}
          {!initial && (
            <FormGridFull>
              <div className="stack">
                <QuickLinkField projectId={projectId} artefactType="architecture_state" value={quickLinks} onChange={setQuickLinks} />
                <TagField projectId={projectId} artefactType="architecture_state" value={tags} onChange={setTags} components={false} />
              </div>
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions
          error={error} onCancel={onCancel} saveDisabled={!valid}
          onSave={() => onSave({ ...values, name: values.name.trim() }, { quickLinks, tags })}
        />
      </div>
    </Modal>
  );
}
