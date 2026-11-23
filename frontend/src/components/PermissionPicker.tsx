/**
 * Module: components/PermissionPicker
 *
 * A grouped, multi-select checkbox grid over an organisation's valid permission-atom vocabulary, used by
 * `CustomRoleDefinition` create and edit to build a role's `permissions` set. Options are grouped by
 * `Permission.artefact_type` (a `null` type, the short administrative list such as `grant_roles`, groups under
 * "Administrative"), each group a `CollapsibleSection`.
 *
 * A grouped checkbox grid rather than `MultiSelectDropdown`, because a vocabulary of every artefact type, level and
 * sub-type must stay visible while many boxes are ticked across groups. Every `Permission.label` is the
 * server-supplied string (`GET /orgs/{id}/permissions`) and is rendered directly, so the component never hardcodes
 * the permission vocabulary.
 */
import type { ReactNode } from "react";

import type { Permission } from "../api/types";
import { ALL_ARTEFACT_TYPES, activityEntityLabel } from "../api/types";
import { useOrgLabel } from "../context/BrandingContext";
import { CollapsibleSection } from "./CollapsibleSection";

const ADMINISTRATIVE_GROUP_LABEL = "Administrative";
const ALL_TYPES_GROUP_LABEL = "All record types";

/** Groups `permissions` by `artefact_type`, administrative (`artefact_type === null`) permissions last, as
 * `get_all_permissions` orders them. */
function groupByArtefactType(permissions: Permission[]): Array<{ key: string; label: string; items: Permission[] }> {
  const groups = new Map<string, Permission[]>();
  for (const permission of permissions) {
    const key = permission.artefact_type ?? "";
    const existing = groups.get(key);
    if (existing) existing.push(permission);
    else groups.set(key, [permission]);
  }
  // The "every record type" atoms lead: one tick per level covers every type, present and future.
  const orderedKeys = [...groups.keys()].filter((k) => k !== "" && k !== ALL_ARTEFACT_TYPES).sort();
  if (groups.has(ALL_ARTEFACT_TYPES)) orderedKeys.unshift(ALL_ARTEFACT_TYPES);
  if (groups.has("")) orderedKeys.push("");
  return orderedKeys.map((key) => ({ key: key || "__administrative__", label: key, items: groups.get(key) ?? [] }));
}

export function PermissionPicker({
  permissions,
  selected,
  onChange,
  disabled = false,
  emptyState,
}: {
  /** The organisation's full, currently-valid permission-atom vocabulary
   * (`GET /orgs/{id}/permissions`) — never hardcoded by this component. */
  permissions: Permission[];
  /** Currently-selected `Permission.key` values. */
  selected: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
  /** Shown in place of the grouped checkboxes while `permissions` is empty
   * (e.g. still loading) — defaults to a plain text hint. */
  emptyState?: ReactNode;
}) {
  const orgLabel = useOrgLabel();
  const selectedSet = new Set(selected);

  function toggle(key: string, checked: boolean) {
    if (checked) onChange([...selected, key]);
    else onChange(selected.filter((k) => k !== key));
  }

  if (permissions.length === 0) {
    return <p className="text-muted">{emptyState ?? "No permissions available."}</p>;
  }

  const groups = groupByArtefactType(permissions);

  return (
    <div className="stack scroll-region" style={{ gap: "var(--space-3)", maxHeight: "22rem" }}>
      {groups.map((group) => (
        <CollapsibleSection
          key={group.key}
          sectionKey={`permissionPicker.${group.key}`}
          variant="plain"
          title={
            group.label === ALL_ARTEFACT_TYPES
              ? ALL_TYPES_GROUP_LABEL
              : group.label
                ? activityEntityLabel(group.label, orgLabel)
                : ADMINISTRATIVE_GROUP_LABEL
          }
        >
          <div className="stack" style={{ gap: "var(--space-2)" }}>
            {group.items.map((permission) => (
              <label className="checkbox-label" style={{ gap: "var(--space-3)" }} key={permission.key}>
                <input
                  type="checkbox"
                  checked={selectedSet.has(permission.key)}
                  disabled={disabled}
                  onChange={(e) => toggle(permission.key, e.target.checked)}
                  aria-label={permission.label}
                />
                {permission.label}
              </label>
            ))}
          </div>
        </CollapsibleSection>
      ))}
    </div>
  );
}
