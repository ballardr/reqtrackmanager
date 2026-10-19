/**
 * Module: modules/stakeholders/StakeholderFormModal
 *
 * Create/edit dialog for a Stakeholder's content fields (docs/ux-style-guide.md
 * principle 3: a full entity create/edit is a `Modal`). Shared by create and
 * edit (distinguished by whether `initial` is passed) and by the org and
 * project scopes (`scopeLabel` only changes the title).
 *
 * `owner`/`user_id` are not fields here — `StakeholderDetailPage` assigns
 * owner through `RecordPrincipalField`, and `user_id` is set by "create from org
 * user". Influence and Interest use the shared `ScoringLevelPicker` over the
 * org's `stakeholder` scheme (`scheme`; omitted if it couldn't be loaded).
 * Once both are set, the form shows the suggested engagement cadence for that
 * power/interest position next to the cadence field (`loadHint`); it is a hint
 * only and never changes the field. Contact info is Confidential personal
 * data, flagged as such. `change_note` only renders when editing.
 *
 * Groups: when creating and `groups` is given, a `TreeSelect` picks the
 * new stakeholder's groups of this `tier`; they are returned as `group_ids` and
 * applied by the caller after the create (group membership is not part of the
 * stakeholder's own versioned fields). Editing changes groups from the detail
 * page's `StakeholderGroupsField` instead.
 */
import { useEffect, useState } from "react";

import type { ScoringScheme } from "../../api/scoring";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import type { CollectedLink } from "../../api/artefactLinks";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { ScoringLevelPicker } from "../../components/ScoringLevelPicker";
import { TreeSelect } from "../../components/TreeSelect";
import { buildGroupTree, groupSelectNodes } from "./groupTree";
import { TextAreaField, TextField } from "../../components/FormFields";
import type { CadenceHint, Stakeholder, StakeholderFieldValues, StakeholderGroup, TargetCadence } from "./types";
import { GRID_QUADRANT_LABEL, TARGET_CADENCE_LABEL } from "./types";
import { FormActions } from "../../components/FormActions";
import { STAKEHOLDERS_HELP } from "./help";

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
  projectId,
  typeOptions,
  scheme,
  loadHint,
  groups,
  groupTier = "organization",
  error,
  onCancel,
  onSave,
}: {
  initial?: Stakeholder;
  /** e.g. "organisation" / "project", shown in the title of a new stakeholder. */
  scopeLabel: string;
  /** The project a new stakeholder is created in; with it a create form offers the quick-link field. Omit for the organisation scope. */
  projectId?: string;
  /** The enabled types this scope offers; the current type is always kept selectable. */
  typeOptions: { value: string; label: string }[];
  /** The org's `stakeholder` scoring scheme, or `null` to omit the level pickers. */
  scheme: ScoringScheme | null;
  /** Resolves the grid position / suggested cadence for a pair of levels. */
  loadHint: (influenceLevelId: string, interestLevelId: string) => Promise<CadenceHint>;
  /** Every group this view can see; omit (or edit) to leave the group picker out. */
  groups?: StakeholderGroup[];
  /** Which tier of `groups` can be chosen here. */
  groupTier?: "organization" | "project";
  error?: string | null;
  onCancel: () => void;
  onSave: (values: StakeholderFieldValues & { group_ids?: string[] }, quickLinks: CollectedLink[], tags: string[]) => void;
}) {
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);
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

  function save(activate = false) {
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
      ...(activate ? { activate: true } : {}),
      ...(!initial && groups ? { group_ids: groupIds } : {}),
      ...(Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, fields[f.key] ?? ""])) as Record<string, string>),
    } as StakeholderFieldValues, quickLinks, tags);
  }

  return (
    <Modal title={initial ? `Edit ${initial.name}` : `New Stakeholder (${scopeLabel})`} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <TextField helpNotNeeded label="Name" ariaLabel="Stakeholder name" value={name} onChange={setName} />
          <LabeledSelect helpNotNeeded label="Type" value={typeId} onChange={setTypeId} options={options} placeholder="No type" />
          <TextField helpNotNeeded label="Role" value={role} onChange={setRole} />
          <TextField helpNotNeeded label="Organisation / group" value={group} onChange={setGroup} />
          {influenceAxis && interestAxis && (
            <>
              <ScoringLevelPicker axis={influenceAxis} value={influence} onChange={setInfluence} />
              <ScoringLevelPicker axis={interestAxis} value={interest} onChange={setInterest} />
            </>
          )}
          <div className="stack" style={{ gap: "0.25rem" }}>
            <LabeledSelect help={STAKEHOLDERS_HELP.stakeholderCadence}
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
          {!initial && groups && groups.length > 0 && (
            <div className="stack" style={{ gap: "0.25rem" }}>
              <span>Groups</span>
              <TreeSelect
                triggerLabel={groupTier === "project" ? "Project groups" : "Organisation groups"}
                nodes={groupSelectNodes(buildGroupTree(groups), groupTier, "Organisation groups are changed from the organisation view.")}
                selectedIds={groupIds} onChange={setGroupIds} emptyLabel="No groups"
              />
            </div>
          )}
          {TEXT_FIELDS.map((f) => (
            <FormGridFull key={f.key}>
              <TextAreaField helpNotNeeded
                label={f.label} rows={f.rows} value={fields[f.key] ?? ""}
                onChange={(value) => setFields((prev) => ({ ...prev, [f.key]: value }))}
              />
            </FormGridFull>
          ))}
          <FormGridFull>
            <TextAreaField helpNotNeeded
              label="Contact / reference information" value={contact} onChange={setContact}
              hint="Confidential personal data. Everyone who can see this stakeholder can read it."
            />
          </FormGridFull>
          <FormGridFull>
            <TextAreaField helpNotNeeded
              label="Availability constraints" value={availability} onChange={setAvailability}
              hint="What limits how often they will engage (their side, not ours)."
            />
          </FormGridFull>
          {initial && <FormGridFull><TextField helpNotNeeded label="Change note (optional)" ariaLabel="Change note" value={changeNote} onChange={setChangeNote} /></FormGridFull>}
          {!initial && projectId && (
            <FormGridFull>
              <div className="stack">
                <QuickLinkField projectId={projectId} artefactType="stakeholder" value={quickLinks} onChange={setQuickLinks} />
                <TagField projectId={projectId} artefactType="stakeholder" value={tags} onChange={setTags} />
              </div>
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions
          error={error} onCancel={onCancel} onSave={() => save()} saveDisabled={!valid}
          onSaveAndActivate={initial ? undefined : () => save(true)}
        />
      </div>
    </Modal>
  );
}
