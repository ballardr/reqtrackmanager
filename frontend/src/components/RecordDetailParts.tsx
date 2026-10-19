/**
 * Module: components/RecordDetailParts
 *
 * Small presentational pieces the versioned-record detail pages (Stakeholders'
 * Persona/Stakeholder/Need, Risk Management's Risk) render the same way: a
 * labelled read-only field, a labelled "who" picker (a `PrincipalPicker`, or
 * a `PrincipalBadge` when the record is read-only), and the version-history table.
 * Kept together so the pages differ only in which fields they show, not in how
 * a field looks.
 */
import type { ReactNode } from "react";

import type { OrgUser, Principal, PrincipalRef } from "../api/types";
import { FieldCaption } from "./FieldHelp";
import type { FieldHelpProps } from "./FieldHelp";
import { PrincipalBadge } from "./PrincipalBadge";
import { PrincipalPicker } from "./PrincipalPicker";

/** A labelled, multi-line read-only value. */
export function RecordField({ label, value }: { label: string; value: string }) {
  return (
    <div className="stack" style={{ gap: "0.15rem" }}>
      <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>{label}</span>
      <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{value}</p>
    </div>
  );
}

/**
 * A labelled bold caption over arbitrary content (the same label style as `RecordField`).
 *
 * @param action A control on the caption's own line, e.g. an `AddPopoverButton`, so adding to a
 *   list costs no extra row.
 * @param help The group's `(?)` help text; `helpNotNeeded` for a self-explanatory group (see `FieldHelp`).
 */
export function RecordFieldGroup({
  label, children, gap = "0.25rem", action, help,
}: FieldHelpProps & { label: string; children: ReactNode; gap?: string; action?: ReactNode }) {
  return (
    <div className="stack" style={{ gap }}>
      <span className="row" style={{ gap: "0.35rem", alignItems: "center" }}>
        <FieldCaption label={label} help={help} muted />
        {action}
      </span>
      {children}
    </div>
  );
}

/**
 * A labelled "who" field: a `PrincipalPicker` (a user, an organisation group and, when `projectId`
 * is given, a project group), or just a `PrincipalBadge` when `readOnly`. An organisation-scoped
 * record passes no `projectId`, so it cannot name a project group.
 *
 * @param principal The field's resolved current value (the record's own `PrincipalOut`).
 * @param projectId The record's project, enabling project-group choices; omit for an organisation-level record.
 * @param onChange Called with the picked principal, or null when unassigned.
 *
 * The picker is the compact one (the value with a (+)/pencil button and an "x"), as on every detail page
 * (docs/ux-style-guide.md, "Show the value, offer the add"); the always-open search box is for create forms.
 */
export function RecordPrincipalField({
  label, ariaLabel, principal, orgUsers, organizationId, projectId, readOnly, onChange,
}: {
  label: string;
  ariaLabel: string;
  principal: Principal | null;
  orgUsers: OrgUser[];
  organizationId?: string;
  projectId?: string;
  readOnly: boolean;
  onChange: (principal: PrincipalRef | null) => void;
}) {
  return (
    <RecordFieldGroup helpNotNeeded label={label}>
      {readOnly ? (
        <PrincipalBadge principal={principal} />
      ) : (
        <PrincipalPicker
          orgUsers={orgUsers} organizationId={organizationId} projectId={projectId}
          kinds={projectId ? undefined : ["user", "org_group"]}
          value={principal} display={principal} onChange={onChange} ariaLabel={ariaLabel} compact
        />
      )}
    </RecordFieldGroup>
  );
}

/**
 * The version-history table, shown once a record has more than one version.
 * Every record kind shows Version, then its own columns, then Changed and
 * Change note.
 *
 * @param columns The kind-specific columns, rendered between Version and Changed.
 */
export function VersionHistoryTable<V extends { id: string; version_number: number; valid_from: string; change_note: string }>({
  versions, columns,
}: {
  versions: V[] | null;
  columns: { header: string; render: (version: V) => ReactNode }[];
}) {
  if (!versions || versions.length <= 1) return null;
  return (
    <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
      <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Versions</h3>
      <table className="table">
        <thead>
          <tr>
            <th>Version</th>
            {columns.map((c) => <th key={c.header}>{c.header}</th>)}
            <th>Changed</th><th>Change note</th>
          </tr>
        </thead>
        <tbody>
          {[...versions].reverse().map((v) => (
            <tr key={v.id}>
              <td>{v.version_number}</td>
              {columns.map((c) => <td key={c.header}>{c.render(v)}</td>)}
              <td>{new Date(v.valid_from).toLocaleString()}</td>
              <td>{v.change_note || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
