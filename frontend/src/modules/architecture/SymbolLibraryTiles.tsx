/**
 * Module: modules/architecture/SymbolLibraryTiles
 *
 * The tile view of the symbol library page: one `TileCard` per symbol with its drawing large enough to recognise, its name and
 * badges, the folder, where it is used and the same actions menu as a table row. A tile reads its drawing only when it scrolls
 * into view, so a library of hundreds does not request them all at once. A symbol that can be filed has a checkbox for the
 * bulk move, as the table's first column does.
 */
import { ActionMenu } from "../../components/ActionMenu";
import { CellText } from "../../components/CellText";
import { InlineCheckbox } from "../../components/FormFields";
import { TileCard, TileGrid } from "../../components/TileCard";
import { LazySymbolImage } from "./SymbolGallery";
import { symbolRowActions, type SymbolRowActionContext } from "./symbolLibraryActions";
import { SymbolBadges, UsedBy } from "./symbolLibraryRows";
import type { SymbolLibraryRow } from "./types";

/**
 * @param rows The loaded rows.
 * @param urlFor The API path of a symbol's content.
 * @param organizationLabel What the organisation is called (its badge in a project).
 * @param actions What the tiles' menus offer, or `null` where the person may not change the library.
 * @param selected The ids chosen for the bulk move.
 * @param onSelectedChange Called with the new set.
 * @param onShowUsage Opens the usage dialog.
 */
export function SymbolLibraryTiles({
  rows, urlFor, organizationLabel, actions, selected, onSelectedChange, onShowUsage,
}: {
  rows: SymbolLibraryRow[];
  urlFor: (id: string) => string;
  organizationLabel: string;
  actions: SymbolRowActionContext | null;
  selected: ReadonlySet<string>;
  onSelectedChange: (next: Set<string>) => void;
  onShowUsage: (row: SymbolLibraryRow) => void;
}) {
  return (
    <TileGrid>
      {rows.map((row) => (
        <TileCard
          key={row.id} title={row.name}
          titleBadges={<SymbolBadges row={row} organizationLabel={organizationLabel} inProject={actions?.inProject ?? false} />}
          eyebrow={actions && row.can_file ? (
            <InlineCheckbox
              ariaLabel={`Select ${row.name}`} checked={selected.has(row.id)}
              onChange={(on) => { const next = new Set(selected); if (on) next.add(row.id); else next.delete(row.id); onSelectedChange(next); }}
            />
          ) : undefined}
          actions={actions ? <ActionMenu triggerLabel={`Actions for ${row.name}`} items={symbolRowActions(row, actions)} /> : undefined}
        >
          <div className="row" style={{ gap: "var(--space-3)", flexWrap: "nowrap", alignItems: "center" }}>
            <LazySymbolImage src={urlFor(row.id)} size={56} />
            <div className="stack" style={{ gap: "var(--space-1)", minWidth: 0, flex: "1 1 0" }}>
              {row.folder_path ? <CellText className="text-muted" lines={2}>{row.folder_path}</CellText> : <span className="text-muted">No folder</span>}
              <UsedBy row={row} onShow={onShowUsage} />
            </div>
          </div>
        </TileCard>
      ))}
    </TileGrid>
  );
}
