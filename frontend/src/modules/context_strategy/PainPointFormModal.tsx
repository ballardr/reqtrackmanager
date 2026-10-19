/**
 * Module: modules/context_strategy/PainPointFormModal
 *
 * Create/edit dialog for a Pain Point's content fields — mirrors `StrategyFormModal.tsx`'s
 * "shared by create and edit, distinguished by whether `initial` is passed"
 * convention.
 *
 * **No create/edit field-set asymmetry, unlike `StrategyFormModal`'s
 * `change_note` (Decided by: Agent).** Pain Point has no version table, so there is no "explain what changed"
 * concept to add in edit mode — `PainPointFieldValues` is identical for both
 * calls.
 *
 * **Scoring at creation (Decided by: Agent).** A create form also offers Severity, Frequency and
 * Confidence through `PainPointScoreFields`, the grid the detail page's scoring panel uses, so a
 * Pain Point need not be reopened to be scored. It appears only when the caller may score (the
 * `scoring` prop); an existing record is scored in its panel, not in this form.
 *
 * **`owner` is deliberately not a field here (Decided by: Agent).**
 * Source overview §6.5 places "Assign owner" on the manager tier as its own
 * distinct capability, not part of the create/edit content form — see
 * `types.ts`'s own docstring on `PainPointFieldValues`. `PainPointDetailPage.tsx`
 * assigns it directly via its own `PrincipalPicker` control instead.
 */
import { useState } from "react";

import type { CollectedLink } from "../../api/artefactLinks";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { FormActions } from "../../components/FormActions";
import { DateField, TextAreaField, TextField } from "../../components/FormFields";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { ToggleSwitch } from "../../components/ToggleSwitch";
import type { ScoringScheme } from "../../api/scoring";
import { PainPointScoreFields } from "./PainPointScoreFields";
import { scoreInputsFromDraft, visibleScoreRows, type ScoreDraft, type ScoreMode, type ScoreRow } from "./painPointScoreDraft";
import { PAIN_POINT_PRIORITY_LABEL } from "./types";
import type {
  EffectivePainPointType, PainPoint, PainPointFieldValues, PainPointPriority, PainPointScoringTarget,
} from "./types";

const TEXT_FIELDS: { key: keyof PainPointFieldValues; label: string; rows: number }[] = [
  { key: "description", label: "Description", rows: 3 },
  { key: "source", label: "Source", rows: 2 },
  { key: "impact", label: "Impact", rows: 2 },
  { key: "evidence", label: "Evidence", rows: 2 },
];

export function PainPointFormModal({
  initial,
  projectId,
  types,
  scoring,
  error,
  onCancel,
  onSave,
}: {
  initial?: PainPoint;
  /** The project the Pain Point is created in; with it a create form offers the quick-link field
   * (persona first). Ignored when editing: an existing record's links live in its Links panel. */
  projectId?: string;
  /** This project's effective Pain Point type list (`projectPainPointApi.
   * listTypes`) — only enabled types are offered, plus `initial`'s own
   * current type even if it has since been disabled (so editing an existing
   * Pain Point never silently drops its own type from the picker). */
  types: EffectivePainPointType[];
  /** Create only: the scoring scheme and the personas on offer, passed only when the caller may
   * score (a Pain Point manager). Without it the form has no scoring section, since scoring is a
   * triage-tier action that the server would refuse. */
  scoring?: { scheme: ScoringScheme; targets: PainPointScoringTarget[] };
  error?: string | null;
  onCancel: () => void;
  onSave: (values: PainPointFieldValues, quickLinks: CollectedLink[], tags: string[]) => void;
}) {
  const [painPointTypeId, setPainPointTypeId] = useState(initial?.pain_point_type_id ?? "");
  const [title, setTitle] = useState(initial?.title ?? "");
  const [priority, setPriority] = useState<PainPointPriority>(initial?.priority ?? "medium");
  const [dateIdentified, setDateIdentified] = useState(initial?.date_identified ?? "");
  const [isIntentional, setIsIntentional] = useState(initial?.is_intentional ?? false);
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [scoreMode, setScoreMode] = useState<ScoreMode>("all");
  const [scoreDraft, setScoreDraft] = useState<ScoreDraft>({});
  const [fields, setFields] = useState<Record<string, string>>(() =>
    Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, (initial?.[f.key as keyof PainPoint] as string | undefined) ?? ""]))
  );

  const typeOptions = types
    .filter((t) => t.is_enabled || t.id === initial?.pain_point_type_id)
    .map((t) => ({ value: t.id, label: t.is_enabled ? t.name : `${t.name} (disabled)` }));

  const scoreAxes = Object.fromEntries((scoring?.scheme.axes ?? []).map((a) => [a.key, a]));
  const personaRows: ScoreRow[] = (scoring?.targets ?? [])
    .filter((t) => t.is_active)
    .map((t) => ({ key: t.id, label: t.label, note: t.weight !== null ? `weight ${t.weight}` : "", retired: false, unavailable: false }));

  function save() {
    const scores = !initial && scoring
      ? scoreInputsFromDraft(scoreDraft, visibleScoreRows(scoreMode, personaRows))
      : undefined;
    onSave({
      pain_point_type_id: painPointTypeId,
      title,
      priority,
      date_identified: dateIdentified || null,
      is_intentional: isIntentional,
      ...(scores ? { scores } : {}),
      ...(Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, fields[f.key] ?? ""])) as Record<string, string>),
    } as PainPointFieldValues, quickLinks, tags);
  }

  const valid = painPointTypeId !== "" && title.trim() !== "";

  return (
    <Modal title={initial ? `Edit ${initial.title}` : "New Pain Point"} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <LabeledSelect helpNotNeeded label="Type" value={painPointTypeId} onChange={setPainPointTypeId} options={typeOptions} />
          <LabeledSelect helpNotNeeded
            label="Priority"
            value={priority}
            onChange={(v) => setPriority(v as PainPointPriority)}
            options={Object.entries(PAIN_POINT_PRIORITY_LABEL).map(([value, label]) => ({ value, label }))}
          />
          <FormGridFull>
            <TextField helpNotNeeded label="Title" ariaLabel="Pain Point title" value={title} onChange={setTitle} />
          </FormGridFull>
          {TEXT_FIELDS.map((f) => (
            <FormGridFull key={f.key}>
              <TextAreaField helpNotNeeded
                label={f.label} rows={f.rows} value={fields[f.key] ?? ""}
                onChange={(value) => setFields((prev) => ({ ...prev, [f.key]: value }))}
              />
            </FormGridFull>
          ))}
          <DateField helpNotNeeded
            label={`Date identified${!initial ? " (defaults to today if left blank)" : ""}`} ariaLabel="Date identified"
            value={dateIdentified} onChange={setDateIdentified}
          />
          <FormGridFull>
            <div className="row" style={{ alignItems: "center", gap: "0.5rem" }}>
              <ToggleSwitch checked={isIntentional} onChange={setIsIntentional} label="Intentional limitation" />
              <span>
                Intentional limitation
                <span className="text-muted"> — a deliberate restriction (e.g. in a lower tier). Scored, but kept out of fix rankings.</span>
              </span>
            </div>
          </FormGridFull>
          {!initial && scoring && (
            <FormGridFull>
              <section className="stack" aria-label="Scoring">
                <strong>Scoring (optional)</strong>
                <PainPointScoreFields
                  axes={scoreAxes} personaRows={personaRows} mode={scoreMode} onModeChange={setScoreMode}
                  draft={scoreDraft} onDraftChange={setScoreDraft}
                />
              </section>
            </FormGridFull>
          )}
          {!initial && projectId && (
            <FormGridFull>
              <div className="stack">
                <QuickLinkField
                projectId={projectId} artefactType="pain_point" preferredType="persona" value={quickLinks}
                onChange={setQuickLinks}
              />
                <TagField projectId={projectId} artefactType="pain_point" value={tags} onChange={setTags} />
              </div>
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={save} saveDisabled={!valid} />
      </div>
    </Modal>
  );
}
