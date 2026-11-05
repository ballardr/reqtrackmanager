/**
 * Module: components/ScoringAxisFormModal
 *
 * The create/edit dialog for a scoring axis an organisation or project defines (generic scoring-matrix core). Create
 * takes the name, the guidance and the axis's first levels; edit changes the name and guidance only, because levels
 * are edited in the scheme editor's Levels section like every other axis's. Saving is the caller's: it makes the
 * call and reports a failure through `error`.
 */
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import type { ScoringAxis, ScoringAxisInput, ScoringLevelSpec } from "../api/scoring";
import { useStrings } from "../context/TerminologyContext";
import { FormActions } from "./FormActions";
import { InlineTextInput, TextAreaField, TextField } from "./FormFields";
import { Modal } from "./Modal";

interface LevelDraft {
  name: string;
  weight: string;
  description: string;
}

const MIN_LEVELS = 2;
const MAX_LEVELS = 12;

/** The axis a person is shown to start from: two blank levels. */
const blankLevels = (): LevelDraft[] => [
  { name: "", weight: "", description: "" },
  { name: "", weight: "", description: "" },
];

/** The level specs the drafts describe, or `null` while a name or weight is missing, or names or weights repeat. */
function levelSpecs(drafts: LevelDraft[]): ScoringLevelSpec[] | null {
  const specs = drafts.map((d) => ({ name: d.name.trim(), weight: Number(d.weight), description: d.description.trim() || null }));
  const valid = specs.length >= MIN_LEVELS && specs.length <= MAX_LEVELS
    && specs.every((s) => s.name && isPositive(s.weight))
    && new Set(specs.map((s) => s.name.toLowerCase())).size === specs.length
    && new Set(specs.map((s) => s.weight)).size === specs.length;
  return valid ? specs : null;
}

function isPositive(weight: number): boolean {
  return Number.isFinite(weight) && weight > 0;
}

/**
 * @param initial The axis being edited; omit to define a new one.
 * @param error A save error to show beside the actions.
 * @param onCancel Closes the dialog.
 * @param onSave Called with the values to save (`levels` is empty when editing, where it is ignored).
 */
export function ScoringAxisFormModal({
  initial, error, onCancel, onSave,
}: {
  initial?: ScoringAxis;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: ScoringAxisInput) => void;
}) {
  const strings = useStrings();
  const [label, setLabel] = useState(initial?.label ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [levels, setLevels] = useState<LevelDraft[]>(blankLevels);
  const specs = initial ? [] : levelSpecs(levels);
  const valid = label.trim() !== "" && specs !== null;

  function setLevel(index: number, patch: Partial<LevelDraft>) {
    setLevels((all) => all.map((l, i) => (i === index ? { ...l, ...patch } : l)));
  }

  return (
    <Modal title={initial ? "Edit scoring axis" : "Add a scoring axis"} onClose={onCancel}>
      <div className="stack">
        <TextField label="Name" required value={label} onChange={setLabel} help={strings.help.scoringAxisName} inputProps={{ maxLength: 100 }} />
        <TextAreaField label="Guidance" value={description} onChange={setDescription} help={strings.help.scoringAxisDescription} />
        {initial ? (
          <p className="text-muted" style={{ margin: 0 }}>Edit this axis's levels in the Levels section.</p>
        ) : (
          <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0, gap: "var(--space-2)" }}>
            <legend><strong>Levels</strong></legend>
            <span className="text-muted">
              Two to {MAX_LEVELS} levels, each with its own name and weight. The highest weight is the axis's top level.
            </span>
            {levels.map((l, i) => (
              <div key={i} className="row" style={{ gap: "var(--space-2)", flexWrap: "nowrap" }}>
                <InlineTextInput ariaLabel={`Level ${i + 1} name`} placeholder="Level name" value={l.name} maxWidth={180} onChange={(name) => setLevel(i, { name })} />
                <InlineTextInput ariaLabel={`Level ${i + 1} weight`} placeholder="Weight" type="number" value={l.weight} maxWidth={90} onChange={(weight) => setLevel(i, { weight })} />
                <InlineTextInput ariaLabel={`Level ${i + 1} guidance`} placeholder="Guidance" value={l.description} onChange={(description) => setLevel(i, { description })} />
                <button
                  type="button" className="btn btn-icon" aria-label={`Remove level ${i + 1}`} title={levels.length <= MIN_LEVELS ? "At least 2 are required." : "Remove level"}
                  disabled={levels.length <= MIN_LEVELS} onClick={() => setLevels((all) => all.filter((_, j) => j !== i))}
                >
                  <Trash2 />
                </button>
              </div>
            ))}
            <div>
              <button type="button" className="btn" disabled={levels.length >= MAX_LEVELS}
                onClick={() => setLevels((all) => [...all, { name: "", weight: "", description: "" }])}>
                <Plus /> Add level
              </button>
            </div>
          </fieldset>
        )}
        <FormActions
          error={error} onCancel={onCancel} saveDisabled={!valid}
          onSave={() => onSave({ label: label.trim(), description: description.trim() || null, levels: specs ?? [] })}
        />
      </div>
    </Modal>
  );
}
