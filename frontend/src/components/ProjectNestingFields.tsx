/**
 * Module: components/ProjectNestingFields
 *
 * The fields that place a project under a parent: the parent itself, whether access is inherited from it,
 * and, for the role-mirroring mode, which role is mirrored. One component for the New project dialog (inside a
 * collapsed "Nesting" group) and the project settings page, so the two cannot drift.
 *
 * Responsibilities: draw the three fields, and reset an elevated inheritance mode when the parent changes, so a
 * mode confirmed for one parent is never carried over to another. Confirmation of an elevated mode, and what
 * is stored, stay with the caller: `onModeChange` is called with the requested mode and the caller decides
 * whether to ask first (`utils/projectInheritance`).
 */
import type { ProjectRole, ProjectRoleInheritanceMode } from "../api/types";
import { PROJECT_ROLE_INHERITANCE_MODE_LABEL, PROJECT_ROLE_LABEL } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { MODES_NEEDING_CONFIRMATION } from "../utils/projectInheritance";
import { LabeledSelect } from "./LabeledSelect";

const MIRRORABLE_ROLES: ProjectRole[] = ["project_manager", "project_administrator", "stakeholder"];

/**
 * @param parentProjectId The chosen parent's id; empty for a top-level project.
 * @param parentOptions The projects that may be chosen as the parent.
 * @param onParentChange Called with the new parent id (empty for none).
 * @param mode The current inheritance mode.
 * @param onModeChange Called with the requested mode; also called with `"none"` when a parent change resets an elevated mode.
 * @param filterRole The role mirrored by `mirror_role`.
 * @param onFilterRoleChange Called with the newly chosen mirrored role.
 */
export function ProjectNestingFields({
  parentProjectId, parentOptions, onParentChange, mode, onModeChange, filterRole, onFilterRoleChange,
}: {
  parentProjectId: string;
  parentOptions: { id: string; name: string }[];
  onParentChange: (id: string) => void;
  mode: ProjectRoleInheritanceMode;
  onModeChange: (mode: ProjectRoleInheritanceMode) => void;
  filterRole: ProjectRole;
  onFilterRoleChange: (role: ProjectRole) => void;
}) {
  const strings = useStrings();
  return (
    <div className="form-grid" style={{ "--form-grid-min": "18rem" } as React.CSSProperties}>
      <LabeledSelect help={strings.help.projectParent}
        label={strings.projects.parentProject}
        value={parentProjectId}
        onChange={(next) => {
          onParentChange(next);
          if (MODES_NEEDING_CONFIRMATION.includes(mode)) onModeChange("none");
        }}
        options={parentOptions.map((p) => ({ value: p.id, label: p.name }))}
        placeholder={strings.projects.noParent}
      />
      {parentProjectId && (
        <>
          <LabeledSelect help={strings.help.projectInheritAccess}
            label={strings.projects.inheritFromParent}
            value={mode}
            onChange={(next) => onModeChange(next as ProjectRoleInheritanceMode)}
            options={(Object.keys(PROJECT_ROLE_INHERITANCE_MODE_LABEL) as ProjectRoleInheritanceMode[]).map((m) => ({
              value: m, label: PROJECT_ROLE_INHERITANCE_MODE_LABEL[m],
            }))}
            placeholder={null}
          />
          {mode === "mirror_role" && (
            <LabeledSelect help={strings.help.projectRoleToMirror}
              label={strings.projects.inheritModeFilterRole}
              value={filterRole}
              onChange={(next) => onFilterRoleChange(next as ProjectRole)}
              options={MIRRORABLE_ROLES.map((r) => ({ value: r, label: PROJECT_ROLE_LABEL[r] }))}
              placeholder={null}
            />
          )}
        </>
      )}
    </div>
  );
}
