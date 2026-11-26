/**
 * Module: modules/traceability/ApproverRolesField
 *
 * The roles an approval policy names, as a labelled multi-select, and the chips that show a chosen set in a table cell.
 *
 * Responsibilities:
 * - `ApproverRolesField`: list the roles the organisation offers under their kind (project, module, custom), with
 *   where each is granted, and report the chosen set; a chosen role that is no longer offered stays listed under its key
 *   so it can be removed.
 * - `ApproverRoleChips`: show a set of roles as pills, or a muted "None".
 *
 * Design decisions: a role's identity is its kind and key, never its label (two kinds can share a label). The field takes
 * the whole option list and does not know which record type it edits.
 *
 * Dependencies: `MultiSelectDropdown`, `FieldShell`, `Badge`.
 */
import { useId } from "react";

import { Badge } from "../../components/Badge";
import { FieldShell } from "../../components/FieldHelp";
import { MultiSelectDropdown, type MultiSelectOption } from "../../components/MultiSelectDropdown";
import { APPROVER_ROLE_KIND_LABEL, APPROVER_ROLE_KIND_ORDER, APPROVER_ROLE_SCOPE_LABEL, roleId } from "./approverRoles";
import type { ApproverRole, ApproverRoleOption, ApproverRoleOut } from "./types";

const NO_LONGER_OFFERED = "No longer offered";

/**
 * @param label The visible caption.
 * @param help The field's `(?)` help text.
 * @param options The roles the policy may name.
 * @param value The chosen roles.
 * @param onChange Called with the new chosen set after a role is ticked or cleared.
 * @param disabled Makes every role unavailable (a read-only view).
 */
export function ApproverRolesField({
  label, help, options, value, onChange, disabled,
}: {
  label: string;
  help: string;
  options: ApproverRoleOption[];
  value: ApproverRole[];
  onChange: (next: ApproverRole[]) => void;
  disabled?: boolean;
}) {
  const controlId = useId();
  const chosen = new Set(value.map(roleId));
  const offered = new Set(options.map(roleId));

  function toggle(role: ApproverRole) {
    const id = roleId(role);
    onChange(chosen.has(id) ? value.filter((v) => roleId(v) !== id) : [...value, { kind: role.kind, key: role.key }]);
  }

  const rows: MultiSelectOption[] = [];
  for (const kind of APPROVER_ROLE_KIND_ORDER) {
    options.filter((o) => o.kind === kind).forEach((role, index) => {
      rows.push({
        value: roleId(role), label: role.label, hint: APPROVER_ROLE_SCOPE_LABEL[role.scope], checked: chosen.has(roleId(role)),
        optionLabel: `${label}: ${role.label}`, section: index === 0 ? APPROVER_ROLE_KIND_LABEL[kind] : undefined,
        disabled, onToggle: () => toggle(role),
      });
    });
  }
  value.filter((v) => !offered.has(roleId(v))).forEach((role, index) => {
    rows.push({
      value: roleId(role), label: role.key, checked: true, optionLabel: `${label}: ${role.key}`,
      section: index === 0 ? NO_LONGER_OFFERED : undefined, disabled, onToggle: () => toggle(role),
    });
  });

  return (
    <FieldShell label={label} controlId={controlId} help={help}>
      <MultiSelectDropdown id={controlId} triggerLabel={label} options={rows} emptyLabel="None" filterable={rows.length > 8} summaryMaxLength={60} summaryCount={(n) => `${n} roles`} />
    </FieldShell>
  );
}

/**
 * @param roles The roles to show.
 * @returns The roles as pills in a row that wraps, or a muted "None" when there are none.
 */
export function ApproverRoleChips({ roles }: { roles: ApproverRoleOut[] }) {
  if (roles.length === 0) return <span className="text-muted">None</span>;
  return (
    <div className="row" style={{ gap: "var(--space-1)" }}>
      {roles.map((role) => <Badge key={roleId(role)}>{role.label}</Badge>)}
    </div>
  );
}
