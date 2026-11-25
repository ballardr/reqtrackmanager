/**
 * Module: modules/architecture/symbolLibraryRows
 *
 * What one symbol of the library page is drawn with in both views (table and tiles), so the two cannot drift. The row's
 * actions are in `symbolLibraryActions`.
 * - `UsedBy`: the owners' names when one or two, else "N records", opening the usage dialog; nothing used is a dash.
 * - `SymbolBadges`: Built-in and the tier (the organisation's, or inherited from a parent project) beside a name.
 */
import { Badge } from "../../components/Badge";
import { CellText } from "../../components/CellText";
import { Tooltip } from "../../components/Tooltip";
import { recordsText } from "./symbolLibraryActions";
import type { SymbolLibraryRow } from "./types";

/**
 * @param row The symbol.
 * @param onShow Opens the usage dialog for the symbol.
 */
export function UsedBy({ row, onShow }: { row: SymbolLibraryRow; onShow: (row: SymbolLibraryRow) => void }) {
  if (row.usage_count === 0) return <span className="text-muted">—</span>;
  const text = row.used_by.length > 0 ? row.used_by.join(", ") : recordsText(row.usage_count);
  const label = `Show where ${row.name} is used`;
  return (
    <Tooltip label={label}>
      <button type="button" className="btn btn-sm" aria-label={`${label} (${text})`} onClick={() => onShow(row)} style={{ maxWidth: "11rem" }}>
        <CellText>{text}</CellText>
      </button>
    </Tooltip>
  );
}

/**
 * @param row The symbol.
 * @param organizationLabel What the organisation is called (the badge on its symbols in a project).
 * @param inProject Whether the page is a project's (an organisation's own page needs no tier badge).
 */
export function SymbolBadges({ row, organizationLabel, inProject }: { row: SymbolLibraryRow; organizationLabel: string; inProject: boolean }) {
  return (
    <>
      {row.is_builtin && <Badge tone="muted">Built-in</Badge>}
      {inProject && row.tier === "organization" && <Badge tone="info">{organizationLabel}</Badge>}
      {inProject && row.tier === "inherited" && <Badge tone="info">Inherited</Badge>}
    </>
  );
}
