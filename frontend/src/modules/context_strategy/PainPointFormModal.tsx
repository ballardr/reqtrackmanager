/**
 * Module: modules/context_strategy/PainPointFormModal
 *
 * Create/edit dialog for a Pain Point's content fields (docs/plans/module-
 * 01-context-and-strategy-plan.md Phase 7.3) — mirrors `StrategyFormModal.tsx`'s
 * "shared by create and edit, distinguished by whether `initial` is passed"
 * convention.
 *
 * **No create/edit field-set asymmetry, unlike `StrategyFormModal`'s
 * `change_note` (Decided by: Agent).** Pain Point has no version table
 * (Phase 3's own scope decision), so there is no "explain what changed"
 * concept to add in edit mode — `PainPointFieldValues` is identical for both
 * calls.
 *
 * **`owner_id` is deliberately not a field here (Decided by: Agent).**
 * Source overview §6.5 places "Assign owner" on the manager tier as its own
 * distinct capability, not part of the create/edit content form — see
 * `types.ts`'s own docstring on `PainPointFieldValues`. `PainPointDetailPage.tsx`
 * assigns it directly via its own `AssigneePicker` control instead.
 */
import { useState } from "react";

import { Modal } from "../../components/Modal";
import { LabeledSelect } from "../../components/LabeledSelect";
import { ToggleSwitch } from "../../components/ToggleSwitch";
import { PAIN_POINT_PRIORITY_LABEL } from "./types";
import type { EffectivePainPointType, PainPoint, PainPointFieldValues, PainPointPriority } from "./types";

const TEXT_FIELDS: { key: keyof PainPointFieldValues; label: string; rows: number }[] = [
  { key: "description", label: "Description", rows: 3 },
  { key: "source", label: "Source", rows: 2 },
  { key: "impact", label: "Impact", rows: 2 },
  { key: "evidence", label: "Evidence", rows: 2 },
];

export function PainPointFormModal({
  initial,
  types,
  error,
  onCancel,
  onSave,
}: {
  initial?: PainPoint;
  /** This project's effective Pain Point type list (`projectPainPointApi.
   * listTypes`) — only enabled types are offered, plus `initial`'s own
   * current type even if it has since been disabled (so editing an existing
   * Pain Point never silently drops its own type from the picker). */
  types: EffectivePainPointType[];
  error?: string | null;
  onCancel: () => void;
  onSave: (values: PainPointFieldValues) => void;
}) {
  const [painPointTypeId, setPainPointTypeId] = useState(initial?.pain_point_type_id ?? "");
  const [title, setTitle] = useState(initial?.title ?? "");
  const [priority, setPriority] = useState<PainPointPriority>(initial?.priority ?? "medium");
  const [dateIdentified, setDateIdentified] = useState(initial?.date_identified ?? "");
  const [isIntentional, setIsIntentional] = useState(initial?.is_intentional ?? false);
  const [fields, setFields] = useState<Record<string, string>>(() =>
    Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, (initial?.[f.key as keyof PainPoint] as string | undefined) ?? ""]))
  );

  const typeOptions = types
    .filter((t) => t.is_enabled || t.id === initial?.pain_point_type_id)
    .map((t) => ({ value: t.id, label: t.is_enabled ? t.name : `${t.name} (disabled)` }));

  function save() {
    onSave({
      pain_point_type_id: painPointTypeId,
      title,
      priority,
      date_identified: dateIdentified || null,
      is_intentional: isIntentional,
      ...(Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, fields[f.key] ?? ""])) as Record<string, string>),
    } as PainPointFieldValues);
  }

  const valid = painPointTypeId !== "" && title.trim() !== "";

  return (
    <Modal title={initial ? `Edit ${initial.title}` : "New Pain Point"} onClose={onCancel} size="lg">
      <div className="stack">
        <LabeledSelect label="Type" value={painPointTypeId} onChange={setPainPointTypeId} options={typeOptions} />
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Title</span>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Pain Point title" />
        </label>
        {TEXT_FIELDS.map((f) => (
          <label key={f.key} className="stack" style={{ gap: "0.25rem" }}>
            <span>{f.label}</span>
            <textarea
              className="input"
              rows={f.rows}
              value={fields[f.key] ?? ""}
              onChange={(e) => setFields((prev) => ({ ...prev, [f.key]: e.target.value }))}
              aria-label={f.label}
            />
          </label>
        ))}
        <LabeledSelect
          label="Priority"
          value={priority}
          onChange={(v) => setPriority(v as PainPointPriority)}
          options={Object.entries(PAIN_POINT_PRIORITY_LABEL).map(([value, label]) => ({ value, label }))}
        />
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Date identified{!initial && " (defaults to today if left blank)"}</span>
          <input
            className="input" type="date" value={dateIdentified}
            onChange={(e) => setDateIdentified(e.target.value)} aria-label="Date identified"
          />
        </label>
        <div className="row" style={{ alignItems: "center", gap: "0.5rem" }}>
          <ToggleSwitch checked={isIntentional} onChange={setIsIntentional} label="Intentional limitation" />
          <span>
            Intentional limitation
            <span className="text-muted"> — a deliberate restriction (e.g. in a lower tier). Scored, but kept out of fix rankings.</span>
          </span>
        </div>
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button className="btn btn-primary" disabled={!valid} onClick={save}>Save</button>
        </div>
      </div>
    </Modal>
  );
}
