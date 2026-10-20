import { useRecordCode } from "../hooks/useRecordCode";

/**
 * A record's code as the viewer should see it: `REQ-001`, or `ACME-REQ-001` when the project
 * code is added (outside its own project, when the organisation enforces it, or when the viewer
 * prefers it). Use this, or `useRecordCode` for composed labels, for every shown record code.
 *
 * @param code The record's own code.
 * @param ownerProjectCode The code of the owning project when it is not the one being viewed.
 */
export function RecordCode({ code, ownerProjectCode }: { code: string; ownerProjectCode?: string | null }) {
  const formatted = useRecordCode().code(code, ownerProjectCode);
  return <>{formatted}</>;
}
