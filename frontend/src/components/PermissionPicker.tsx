/**
 * Module: components/PermissionPicker
 *
 * A grouped, multi-select checkbox grid over an organisation's currently-
 * valid permission-atom vocabulary (Fine-Grained Access Control,
 * `docs/plans/core-fine-grained-access-control-plan.md` Phase 0 Q1/Phase 3)
 * — the picker `CustomRoleDefinition` create/edit uses to build up a
 * role's `permissions` set. Options are grouped by `Permission.artefact_type`
 * (a `null` artefact type — the short, hand-maintained administrative list,
 * e.g. `grant_roles` — groups under its own "Administrative" heading),
 * each rendered as its own `CollapsibleSection` so a large vocabulary
 * (every registered artefact type × 4 levels × however many sub-types)
 * doesn't read as one undifferentiated wall of checkboxes.
 *
 * Deliberately the one new, reusable UI shape this phase introduces (no
 * grouped multi-select checkbox grid existed anywhere else in this
 * codebase — `MultiSelectDropdown` is the closest precedent, but that's a
 * closed, compact *dropdown* over a small flat option list, the wrong
 * shape for a vocabulary this size that benefits from staying visible
 * on-page while ticking many boxes across several groups at once). Every
 * `Permission.label` is already a human-readable, server-supplied string
 * (`GET /orgs/{id}/permissions`) — rendered directly, never re-derived
 * from `artefact_type`/`level`/`subtype` client-side, so this component
 * never hardcodes the permission vocabulary itself.
 */
import type { ReactNode } from "react";

import type { Permission } from "../api/types";
import { activityEntityLabel } from "../api/types";
import { useOrgLabel } from "../context/BrandingContext";
import { CollapsibleSection } from "./CollapsibleSection";

const ADMINISTRATIVE_GROUP_LABEL = "Administrative";

/** Groups `permissions` by `artefact_type`, administrative (`artefact_type
 * === null`) permissions last — mirrors `get_all_permissions`'s own
 * server-side ordering (artefact-type atoms first, administrative
 * permissions appended after). */
function groupByArtefactType(permissions: Permission[]): Array<{ key: string; label: string; items: Permission[] }> {
  const groups = new Map<string, Permission[]>();
  for (const permission of permissions) {
    const key = permission.artefact_type ?? "";
    const existing = groups.get(key);
    if (existing) existing.push(permission);
    else groups.set(key, [permission]);
  }
  const orderedKeys = [...groups.keys()].filter((k) => k !== "").sort();
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
    <div className="stack" style={{ gap: "0.5rem", maxHeight: "22rem", overflowY: "auto" }}>
      {groups.map((group) => (
        <CollapsibleSection
          key={group.key}
          sectionKey={`permissionPicker.${group.key}`}
          variant="plain"
          title={group.label ? activityEntityLabel(group.label, orgLabel) : ADMINISTRATIVE_GROUP_LABEL}
        >
          <div className="stack" style={{ gap: "0.35rem" }}>
            {group.items.map((permission) => (
              <label className="row" style={{ gap: "0.5rem" }} key={permission.key}>
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
