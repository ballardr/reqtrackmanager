/**
 * Module: modules/stakeholders/StakeholderFormModal
 *
 * Create/edit dialog for a Stakeholder's content fields (docs/ux-style-guide.md
 * principle 3: a full entity create/edit is a `Modal`). Shared by create and
 * edit (distinguished by whether `initial` is passed) and by the org and
 * project scopes (`scopeLabel` only changes the title).
 *
 * `owner_id`/`user_id` are not fields here — `StakeholderDetailPage` assigns
 * owner through `RecordPersonField`, and `user_id` is set by "create from org
 * user". Influence and Interest use the shared `ScoringLevelPicker` over the
 * org's `stakeholder` scheme (`scheme`; omitted if it couldn't be loaded).
 * Once both are set, the form shows the suggested engagement cadence for that
 * power/interest position next to the cadence field (`loadHint`); it is a hint
 * only and never changes the field. Contact info is Confidential personal
 * data, flagged as such. `change_note` only renders when editing.
 */
import { useEffect, useState } from "react";

import type { ScoringScheme } from "../../api/scoring";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { ScoringLevelPicker } from "../../components/ScoringLevelPicker";
import { TextAreaField, TextField } from "./RecordFormFields";
import type { CadenceHint, Stakeholder, StakeholderFieldValues, TargetCadence } from "./types";
import { GRID_QUADRANT_LABEL, TARGET_CADENCE_LABEL } from "./types";

const TEXT_FIELDS: { key: keyof StakeholderFieldValues; label: string; rows: number }[] = [
  { key: "description", label: "Description", rows: 2 },
  { key: "interests", label: "Interests", rows: 2 },
  { key: "responsibilities", label: "Responsibilities", rows: 2 },
  { key: "goals_needs", label: "Goals and needs", rows: 2 },
  { key: "priorities", label: "Priorities", rows: 2 },
  { key: "constraints", label: "Constraints", rows: 2 },
  { key: "workflows_scenarios", label: "Workflows / use scenarios", rows: 2 },
];

const CADENCE_OPTIONS = Object.entries(TARGET_CADENCE_LABEL).map(([value, label]) => ({ value, label }));

export function StakeholderFormModal({
  initial,
  scopeLabel,
  typeOptions,
  scheme,
  loadHint,
  error,
  onCancel,
  onSave,
}: {
  initial?: Stakeholder;
  /** e.g. "organisation" / "project", shown in the title of a new stakeholder. */
  scopeLabel: string;
  /** The enabled types this scope offers; the current type is always kept selectable. */
  typeOptions: { value: string; label: string }[];
  /** The org's `stakeholder` scoring scheme, or `null` to omit the level pickers. */
  scheme: ScoringScheme | null;
  /** Resolves the grid position / suggested cadence for a pair of levels. */
  loadHint: (influenceLevelId: string, interestLevelId: string) => Promise<CadenceHint>;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: StakeholderFieldValues) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [typeId, setTypeId] = useState(initial?.stakeholder_type_id ?? "");
  const [role, setRole] = useState(initial?.role ?? "");
  const [group, setGroup] = useState(initial?.organisation_group ?? "");
  const [contact, setContact] = useState(initial?.contact_info ?? "");
  const [availability, setAvailability] = useState(initial?.availability_constraints ?? "");
  const [cadence, setCadence] = useState<string>(initial?.target_cadence ?? "");
  const [influence, setInfluence] = useState<string | null>(initial?.influence_level_id ?? null);
  const [interest, setInterest] = useState<string | null>(initial?.interest_level_id ?? null);
  const [changeNote, setChangeNote] = useState("");
  const [fetchedHint, setFetchedHint] = useState<{ key: string; hint: CadenceHint } | null>(null);
  const [fields, setFields] = useState<Record<string, string>>(() =>
    Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, (initial?.[f.key as keyof Stakeholder] as string | undefined) ?? ""])),
  );

  // The hint only applies to the exact pair of levels it was fetched for, so a stale one never shows.
  const hintKey = influence && interest ? `${influence}:${interest}` : null;
  const hint = fetchedHint && fetchedHint.key === hintKey ? fetchedHint.hint : null;
  useEffect(() => {
    if (!influence || !interest) return;
    let active = true;
    const key = `${influence}:${interest}`;
    loadHint(influence, interest).then((h) => active && setFetchedHint({ key, hint: h })).catch(() => undefined);
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [influence, interest]);

  const influenceAxis = scheme?.axes.find((a) => a.key === "influence");
  const interestAxis = scheme?.axes.find((a) => a.key === "interest");
  const valid = name.trim() !== "";

  const options =
    initial?.stakeholder_type_id && !typeOptions.some((o) => o.value === initial.stakeholder_type_id)
      ? [...typeOptions, { value: initial.stakeholder_type_id, label: `${initial.stakeholder_type_name ?? "Current type"} (disabled)` }]
      : typeOptions;

  function save() {
    onSave({
      name: name.trim(),
      stakeholder_type_id: typeId || null,
      role,
      organisation_group: group,
      contact_info: contact,
      availability_constraints: availability,
      target_cadence: (cadence || null) as TargetCadence | null,
      influence_level_id: influence,
      interest_level_id: interest,
      change_note: changeNote,
      ...(Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, fields[f.key] ?? ""])) as Record<string, string>),
    } as StakeholderFieldValues);
  }

  return (
    <Modal title={initial ? `Edit ${initial.name}` : `New Stakeholder (${scopeLabel})`} onClose={onCancel} size="lg">
      <div className="stack">
        <TextField label="Name" ariaLabel="Stakeholder name" value={name} onChange={setName} />
        <LabeledSelect label="Type" value={typeId} onChange={setTypeId} options={options} placeholder="No type" />
        <TextField label="Role" value={role} onChange={setRole} />
        <TextField label="Organisation / group" value={group} onChange={setGroup} />
        {TEXT_FIELDS.map((f) => (
          <TextAreaField
            key={f.key} label={f.label} rows={f.rows} value={fields[f.key] ?? ""}
            onChange={(value) => setFields((prev) => ({ ...prev, [f.key]: value }))}
          />
        ))}
        <TextAreaField
          label="Contact / reference information" value={contact} onChange={setContact}
          hint="Confidential personal data. Everyone who can see this stakeholder can read it."
        />
        {influenceAxis && interestAxis && (
          <div className="row" style={{ gap: "1rem", alignItems: "flex-start" }}>
            <ScoringLevelPicker axis={influenceAxis} value={influence} onChange={setInfluence} />
            <ScoringLevelPicker axis={interestAxis} value={interest} onChange={setInterest} />
          </div>
        )}
        <div className="stack" style={{ gap: "0.25rem" }}>
          <LabeledSelect
            label="Target engagement cadence" value={cadence} onChange={setCadence} options={CADENCE_OPTIONS}
            placeholder="Not set"
          />
          {hint?.suggested_cadence && hint.quadrant && (
            <span className="text-muted" style={{ fontSize: "0.8rem" }} data-testid="cadence-hint">
              Suggested: {TARGET_CADENCE_LABEL[hint.suggested_cadence]} ({GRID_QUADRANT_LABEL[hint.quadrant]}). A suggestion
              only — your choice above is what's saved.
            </span>
          )}
        </div>
        <TextAreaField
          label="Availability constraints" value={availability} onChange={setAvailability}
          hint="What limits how often they will engage (their side, not ours)."
        />
        {initial && <TextField label="Change note (optional)" ariaLabel="Change note" value={changeNote} onChange={setChangeNote} />}
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button className="btn btn-primary" disabled={!valid} onClick={save}>Save</button>
        </div>
      </div>
    </Modal>
  );
}
