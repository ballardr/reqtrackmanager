/**
 * Module: modules/stakeholders/RecordDetailParts
 *
 * Small presentational pieces every record detail page in this module (Persona,
 * Stakeholder) renders the same way: a labelled read-only field, a labelled
 * person picker (an `AssigneePicker`, or a plain name when the record is
 * read-only), and the version-history table. Kept together so the two detail
 * pages differ only in which fields they show, not in how a field looks.
 */
import type { ReactNode } from "react";

import type { OrgUser } from "../../api/types";
import { AssigneePicker } from "../../components/AssigneePicker";

/** A labelled, multi-line read-only value. */
export function RecordField({ label, value }: { label: string; value: string }) {
  return (
    <div className="stack" style={{ gap: "0.15rem" }}>
      <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>{label}</span>
      <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{value}</p>
    </div>
  );
}

/** A labelled bold caption over arbitrary content (the same label style as `RecordField`). */
export function RecordFieldGroup({ label, children, gap = "0.25rem" }: { label: string; children: ReactNode; gap?: string }) {
  return (
    <div className="stack" style={{ gap }}>
      <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>{label}</span>
      {children}
    </div>
  );
}

/**
 * A labelled "which user" field: an `AssigneePicker`, or just the user's name
 * (or "Unassigned") when `readOnly`.
 *
 * @param onChange Called with the picked user id, or "" when unassigned.
 */
export function RecordPersonField({
  label, ariaLabel, userId, orgUsers, organizationId, readOnly, onChange,
}: {
  label: string;
  ariaLabel: string;
  userId: string | null;
  orgUsers: OrgUser[];
  organizationId?: string;
  readOnly: boolean;
  onChange: (userId: string) => void;
}) {
  return (
    <RecordFieldGroup label={label}>
      {readOnly ? (
        <span>{orgUsers.find((u) => u.user_id === userId)?.display_name ?? "Unassigned"}</span>
      ) : (
        <AssigneePicker orgUsers={orgUsers} organizationId={organizationId} assigneeId={userId} onChange={onChange} ariaLabel={ariaLabel} />
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
      <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Version history</h3>
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
