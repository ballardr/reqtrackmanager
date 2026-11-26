/**
 * Module: modules/traceability/ProfileOverviewTab
 *
 * The Overview tab of a governance profile: its details (name, description, mode), the projects it reaches, for an
 * Enforced profile the projects exempt from it, and its effect on every project it reaches (which it binds, which opted
 * in or out).
 *
 * Responsibilities:
 * - Save the details and the reach as two settings groups, each with one Save (`SettingsForm`).
 * - List, add and remove exemptions (Enforced profiles only; Default and Opt-in profiles have no exemption).
 * - Show the impact table, capped at a screenful with Show all.
 *
 * Design decisions: the tab edits a draft of its two groups and reports the profile the server returns through
 * `onChange`, so the page header follows. Each table's column keys are distinct, because the sort of every table is kept in
 * the one `sort` address parameter. Removing an exemption asks first, since it binds the project again at once.
 *
 * Dependencies: `profileApi`, `ProfileTargetsField`, `ProfileExemptionModal`, `DirectoryTable`, `CappedList`.
 */
import { useState } from "react";

import { ActionMenu } from "../../components/ActionMenu";
import { Badge } from "../../components/Badge";
import { CappedList } from "../../components/CappedList";
import { CellText } from "../../components/CellText";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { TextAreaField, TextField } from "../../components/FormFields";
import { LabeledSelect } from "../../components/LabeledSelect";
import { SettingsForm } from "../../components/SettingsForm";
import { cycleSort } from "../../components/sortState";
import { useMutation } from "../../hooks/useMutation";
import { useUrlSort } from "../../hooks/useUrlFilter";
import { sortRows, type SortValue } from "../../utils/sortRows";
import { profileApi } from "./api";
import { GOVERNANCE_HELP } from "./help";
import { ProfileExemptionModal } from "./ProfileExemptionModal";
import { ProfileTargetsField } from "./ProfileTargetsField";
import { PROFILE_MODE_OPTIONS } from "./profileOptions";
import {
  PROFILE_OUTCOME_LABEL, PROFILE_OUTCOME_TONE, type ProfileDetail, type ProfileExemption, type ProfileMode, type ProfileProject,
  type ProfileTarget, type ProfileTargetKind,
} from "./types";

const EXEMPTION_SORT_KEYS = ["exempt_project", "exempt_children", "exempt_reason"] as const;
const IMPACT_SORT_KEYS = ["impact_project", "impact_outcome", "impact_applies", "impact_choice"] as const;
const SORT_KEYS = [...EXEMPTION_SORT_KEYS, ...IMPACT_SORT_KEYS] as const;

/** @param choice A project's stored choice. @returns Its wording in the impact table. */
function choiceText(choice: boolean | null): string {
  if (choice === null) return "No choice";
  return choice ? "Opted in" : "Opted out";
}

/** @param targets Chosen projects. @returns The same set in a stable order, for comparing a draft with the saved reach. */
function normalisedTargets(targets: ProfileTarget[]): string {
  return JSON.stringify([...targets].sort((a, b) => a.project_id.localeCompare(b.project_id)).map((t) => [t.project_id, t.include_children]));
}

/**
 * @param orgId The organisation.
 * @param profile The profile with its effect on projects.
 * @param onChange Called with the profile the server returns after any change.
 */
export function ProfileOverviewTab({
  orgId, profile, onChange,
}: { orgId: string; profile: ProfileDetail; onChange: (profile: ProfileDetail) => void }) {
  const run = useMutation();
  const [sort, setSort] = useUrlSort(SORT_KEYS);
  const [name, setName] = useState(profile.name);
  const [description, setDescription] = useState(profile.description);
  const [mode, setMode] = useState<ProfileMode>(profile.mode);
  const [targetKind, setTargetKind] = useState<ProfileTargetKind>(profile.target_kind);
  const [targets, setTargets] = useState<ProfileTarget[]>(profile.targets.map(({ project_id, include_children }) => ({ project_id, include_children })));
  const [exempting, setExempting] = useState(false);
  const [removing, setRemoving] = useState<ProfileExemption | null>(null);

  const detailsDirty = name.trim() !== profile.name || description.trim() !== profile.description || mode !== profile.mode;
  const savedTargets = profile.targets.map(({ project_id, include_children }) => ({ project_id, include_children }));
  const reachDirty = targetKind !== profile.target_kind
    || (targetKind === "selected_projects" && normalisedTargets(targets) !== normalisedTargets(savedTargets));
  const names = Object.fromEntries(profile.targets.map((t) => [t.project_id, t.project_name]));

  const exemptionColumns: DirectoryColumn<ProfileExemption>[] = [
    { key: "exempt_project", label: "Project", sortable: true, minWidth: "12rem", render: (row) => <CellText lines={2}>{row.project_name}</CellText> },
    { key: "exempt_children", label: "Includes nested projects", sortable: true, render: (row) => (row.include_children ? "Yes" : "No") },
    { key: "exempt_reason", label: "Reason", sortable: true, render: (row) => <CellText lines={2}>{row.reason || "None recorded"}</CellText> },
    {
      key: "actions", label: <span className="sr-only">Actions</span>, width: "3rem",
      render: (row) => (
        <ActionMenu triggerLabel={`Actions for the exemption of ${row.project_name}`} items={[{ label: "Remove exemption", danger: true, onSelect: () => setRemoving(row) }]} />
      ),
    },
  ];
  const exemptionValues: Record<string, (row: ProfileExemption) => SortValue> = {
    exempt_project: (row) => row.project_name, exempt_children: (row) => (row.include_children ? "Yes" : "No"), exempt_reason: (row) => row.reason,
  };
  const impactColumns: DirectoryColumn<ProfileProject>[] = [
    { key: "impact_project", label: "Project", sortable: true, minWidth: "12rem", render: (row) => <CellText lines={2}>{row.project_name}</CellText> },
    {
      key: "impact_outcome", label: "Outcome", sortable: true,
      render: (row) => <Badge tone={PROFILE_OUTCOME_TONE[row.outcome]}>{PROFILE_OUTCOME_LABEL[row.outcome]}</Badge>,
    },
    { key: "impact_applies", label: "Applies", sortable: true, render: (row) => (row.applies ? "Yes" : "No") },
    { key: "impact_choice", label: "Project choice", sortable: true, render: (row) => choiceText(row.choice) },
  ];
  const impactValues: Record<string, (row: ProfileProject) => SortValue> = {
    impact_project: (row) => row.project_name, impact_outcome: (row) => PROFILE_OUTCOME_LABEL[row.outcome],
    impact_applies: (row) => (row.applies ? "Yes" : "No"), impact_choice: (row) => choiceText(row.choice),
  };
  const onSort = (key: string) => setSort((current) => cycleSort(current, key as (typeof SORT_KEYS)[number]));

  return (
    <div className="stack">
      <section className="stack" aria-label="Details">
        <h3 style={{ margin: 0 }}>Details</h3>
        <SettingsForm
          dirty={detailsDirty && name.trim() !== ""} successMessage="Profile saved."
          confirm={{
            when: mode === "enforced" && profile.mode !== "enforced", title: "Enforce profile",
            message: `Enforce ${profile.name}? It binds every project it reaches at once, and only a named exemption lifts it.`,
            confirmLabel: "Enforce profile",
          }}
          onSave={async () => { onChange(await profileApi.update(orgId, profile.id, { name: name.trim(), description: description.trim(), mode })); }}
        >
          <TextField helpNotNeeded required label="Name" value={name} onChange={setName} inputProps={{ maxLength: 200 }} />
          <TextAreaField
            helpNotNeeded plainText="Configuration text shown in lists" label="Description" value={description} onChange={setDescription}
            inputProps={{ maxLength: 500 }}
          />
          <LabeledSelect
            required label="Mode" help={GOVERNANCE_HELP.profileMode} value={mode} placeholder={null} autoWidth
            options={PROFILE_MODE_OPTIONS} onChange={(value) => setMode(value as ProfileMode)}
          />
        </SettingsForm>
      </section>

      <section className="stack" aria-label="Reach">
        <h3 style={{ margin: 0 }}>Reach</h3>
        <SettingsForm
          dirty={reachDirty} successMessage="Reach saved."
          onSave={async () => { onChange(await profileApi.setTargets(orgId, profile.id, targetKind, targetKind === "selected_projects" ? targets : [])); }}
        >
          <ProfileTargetsField orgId={orgId} targetKind={targetKind} targets={targets} names={names} onChange={(kind, next) => { setTargetKind(kind); setTargets(next); }} />
        </SettingsForm>
      </section>

      {profile.mode === "enforced" && (
        <section className="stack" aria-label="Exemptions">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <h3 style={{ margin: 0 }}>Exemptions</h3>
            <button type="button" className="btn" onClick={() => setExempting(true)}>Add exemption</button>
          </div>
          {profile.exemptions.length === 0 ? (
            <p className="text-muted">No project is exempt from this profile.</p>
          ) : (
            <CappedList
              items={sortRows(profile.exemptions, sort, exemptionValues)} noun="exemptions" modalTitle="Exemptions"
              renderList={(items) => (
                <DirectoryTable
                  ariaLabel="Exempt projects" columns={exemptionColumns} rows={items} rowKey={(row) => row.project_id}
                  sort={sort} onSort={onSort} emptyState={null}
                />
              )}
            />
          )}
        </section>
      )}

      <section className="stack" aria-label="Effect on projects">
        <h3 style={{ margin: 0 }}>Effect on projects</h3>
        {profile.projects.length === 0 ? (
          <p className="text-muted">No project is reached by this profile.</p>
        ) : (
          <CappedList
            items={sortRows(profile.projects, sort, impactValues)} noun="projects" modalTitle="Effect on projects"
            renderList={(items) => (
              <DirectoryTable
                ariaLabel="Projects reached by this profile" columns={impactColumns} rows={items} rowKey={(row) => row.project_id}
                sort={sort} onSort={onSort} emptyState={null}
              />
            )}
          />
        )}
      </section>

      {exempting && (
        <ProfileExemptionModal
          orgId={orgId} profileId={profile.id} taken={new Set(profile.exemptions.map((e) => e.project_id))}
          onAdded={(updated) => { setExempting(false); onChange(updated); }} onClose={() => setExempting(false)}
        />
      )}
      {removing && (
        <ConfirmDialog
          title="Remove exemption"
          message={`Remove the exemption of ${removing.project_name}? The profile binds the project again at once.`}
          confirmLabel="Remove exemption"
          onCancel={() => setRemoving(null)}
          onConfirm={() => {
            const target = removing;
            setRemoving(null);
            void run(
              async () => { onChange(await profileApi.removeExemption(orgId, profile.id, target.project_id)); },
              { success: "Exemption removed.", failure: "Could not remove the exemption." },
            );
          }}
        />
      )}
    </div>
  );
}
