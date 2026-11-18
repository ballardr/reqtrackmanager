/**
 * Module: components/ReturnLink
 *
 * The link a record's header draws beside its back link when the person opened the record from another record's page (a
 * state machine diagram opened from a block on a block diagram): "Return to DGM-001 Main system". It leads to where they
 * came from, which the list back link does not, and never depends on browser history, so it still works after a reload
 * or in a new tab (docs/ux-style-guide.md, "Pattern: return to where you came from").
 */
import { Link } from "react-router-dom";

/**
 * @param to The address of the page the person came from.
 * @param label What that page is called ("DGM-001 Main system"); the link reads "Return to {label}".
 */
export function ReturnLink({ to, label }: { to: string; label: string }) {
  return <Link to={to}>Return to {label}</Link>;
}
