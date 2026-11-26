/**
 * Module: modules/traceability/ProfileTargetsField
 *
 * The "which projects does the profile reach" field of a governance profile: the target kind (every project of the
 * organisation, or selected projects) and, for selected projects, a project picker with a "includes nested projects" choice
 * per chosen project. Used by the create dialog and by the Overview tab, so both edit the same shape.
 *
 * Responsibilities:
 * - Show the target kind through its label map and the picker only for selected projects.
 * - List each chosen project with its nested-projects checkbox and a remove control, rows aligned in columns and
 *   unaffected by long project names.
 *
 * Design decisions: the field is controlled and holds no draft; the caller saves. The projects are read once through
 * `useOrgProjectChoices`. A chosen project that is no longer listed (deleted or archived out of the list) keeps its row
 * under the name the profile returned, so the person can still remove it.
 */
import { Trash2 } from "lucide-react";
import { useId } from "react";

import { CellText } from "../../components/CellText";
import { CheckboxField } from "../../components/FormFields";
import { FieldCaption } from "../../components/FieldHelp";
import { IconAction } from "../../components/IconAction";
import { LabeledSelect } from "../../components/LabeledSelect";
import { MultiSelectDropdown } from "../../components/MultiSelectDropdown";
import { GOVERNANCE_HELP } from "./help";
import { PROFILE_TARGET_KIND_OPTIONS } from "./profileOptions";
import type { ProfileTarget, ProfileTargetKind } from "./types";
import { projectChoiceLabel, useOrgProjectChoices } from "./useOrgProjectChoices";

const PROJECTS_HELP = "The projects the profile reaches. Tick Includes nested projects on a project to reach its child projects as well.";

/**
 * @param orgId The organisation whose projects are offered.
 * @param targetKind The chosen kind.
 * @param targets The chosen projects (used only for selected projects).
 * @param names Names of chosen projects by id, for a chosen project that the organisation's list does not hold.
 * @param onChange Called with the new kind and chosen projects after any edit.
 */
export function ProfileTargetsField({
  orgId, targetKind, targets, names = {}, onChange,
}: {
  orgId: string;
  targetKind: ProfileTargetKind;
  targets: ProfileTarget[];
  names?: Record<string, string>;
  onChange: (targetKind: ProfileTargetKind, targets: ProfileTarget[]) => void;
}) {
  const { projects, failed } = useOrgProjectChoices(orgId);
  const pickerId = useId();
  const chosen = new Set(targets.map((t) => t.project_id));
  const labelOf = (projectId: string): string => {
    const found = projects?.find((p) => p.id === projectId);
    return found ? projectChoiceLabel(found) : names[projectId] ?? projectId;
  };

  function toggle(projectId: string) {
    onChange(targetKind, chosen.has(projectId)
      ? targets.filter((t) => t.project_id !== projectId)
      : [...targets, { project_id: projectId, include_children: false }]);
  }

  function setChildren(projectId: string, includeChildren: boolean) {
    onChange(targetKind, targets.map((t) => (t.project_id === projectId ? { ...t, include_children: includeChildren } : t)));
  }

  return (
    <div className="stack">
      <LabeledSelect
        label="Reaches" help={GOVERNANCE_HELP.profileTargetKind} value={targetKind} placeholder={null} autoWidth options={PROFILE_TARGET_KIND_OPTIONS}
        onChange={(value) => onChange(value as ProfileTargetKind, targets)}
      />
      {targetKind === "selected_projects" && (
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <FieldCaption htmlFor={pickerId} label="Projects" help={PROJECTS_HELP} />
          {failed && <span role="alert" style={{ color: "var(--color-danger)" }}>The organisation's projects could not be loaded.</span>}
          <MultiSelectDropdown
            id={pickerId} triggerLabel="Projects" emptyLabel="No projects" filterable summaryMaxLength={60}
            summaryCount={(count) => `${count} projects`}
            options={(projects ?? []).map((p) => ({
              value: p.id, label: projectChoiceLabel(p), checked: chosen.has(p.id), optionLabel: `Reach ${projectChoiceLabel(p)}`,
              onToggle: () => toggle(p.id),
            }))}
          />
          {targets.length > 0 && (
            <ul className="stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: "var(--space-1)" }}>
              {targets.map((target) => (
                <li key={target.project_id} className="row" style={{ flexWrap: "nowrap", justifyContent: "space-between" }} data-stress-row>
                  <span style={{ minWidth: 0, flex: "1 1 auto" }}><CellText>{labelOf(target.project_id)}</CellText></span>
                  <span style={{ flex: "none" }}>
                    <CheckboxField
                      helpNotNeeded label="Includes nested projects" ariaLabel={`Includes nested projects of ${labelOf(target.project_id)}`}
                      checked={target.include_children} onChange={(on) => setChildren(target.project_id, on)}
                    />
                  </span>
                  <span style={{ flex: "none" }}>
                    <IconAction label={`Remove ${labelOf(target.project_id)}`} onClick={() => toggle(target.project_id)}>
                      <Trash2 size={14} />
                    </IconAction>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
