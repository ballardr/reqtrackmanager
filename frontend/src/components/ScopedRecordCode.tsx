import { useRecordOwnerCode } from "../hooks/useOrganizationCode";
import { RecordCode } from "./RecordCode";

/**
 * The code of a record that exists at organisation or project scope (Persona, Stakeholder,
 * Strategy...), as the viewer should see it; a record with no scope is project-scoped. A project-scoped record follows the usual
 * project-code rule; an organisation-owned one is always qualified by the organisation's code
 * (`ACME-PER-001`), because its bare `PER-001` would be ambiguous with a project's own.
 */
export function ScopedRecordCode({
  record,
}: {
  record: { unique_code: string; scope?: string; organization_id?: string | null };
}) {
  return <RecordCode code={record.unique_code} ownerProjectCode={useRecordOwnerCode(record)} />;
}
