/**
 * Module: modules/compliance/OrganisationNote
 *
 * The muted organisation name a Compliance status row carries when the tab reads more than one organisation, so a
 * row never leaves its organisation unstated. Shared by the By standard and Outstanding tabs.
 *
 * Design decisions: renders nothing when the tab reads a single organisation, so callers place it unconditionally.
 */

/**
 * @param name The organisation's name.
 * @param show Whether the tab reads more than one organisation (`ComplianceStatusFrame.showOrg`).
 */
export function OrganisationNote({ name, show }: { name: string; show: boolean }) {
  if (!show) return null;
  return <span className="text-muted"> ({name})</span>;
}
