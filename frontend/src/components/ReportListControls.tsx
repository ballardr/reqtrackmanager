/**
 * Module: components/ReportListControls
 *
 * The search, filters and paging a list of report layouts or report packs shares (Org Admin and Project Admin's
 * Report setup), so the two lists narrow the same way and a third such list reuses it.
 *
 * Responsibilities:
 * - `ReportListControls`: a top filter bar (`FilterPanel layout="top"`) with free-text search and filters for the kind
 *   (layouts: document or table), the folder and, in a project, where it is shared from.
 * The matching rows come from `utils/reportListFilter`, the paging from `hooks/useShowMore`.
 *
 * Design decisions: it is the style guide's directory pattern (search, filters and "Load more"), not a new one; the
 * filter is local state because the list sits inside an admin tab rather than being a page of its own.
 */
import { useStrings } from "../context/TerminologyContext";
import { FILTER_ALL, type ReportListFilter, type ReportListSource } from "../utils/reportListFilter";
import { FilterField, FilterPanel } from "./FilterPanel";

/**
 * @param sectionKey `FilterPanel`'s per-person collapse key; unique per list.
 * @param filter The current filter.
 * @param onChange Called with the new filter.
 * @param folders The folder paths to offer.
 * @param kinds The kind filter's options (value and label), or omit for none.
 * @param showSource Whether to offer the "shared from" filter (a project's list).
 * @param matching How many rows match, and `total` how many there are.
 */
export function ReportListControls({
  sectionKey, filter, onChange, folders, kinds, showSource, matching, total,
}: {
  sectionKey: string;
  filter: ReportListFilter;
  onChange: (filter: ReportListFilter) => void;
  folders: string[];
  kinds?: { value: string; label: string }[];
  showSource: boolean;
  matching: number;
  total: number;
}) {
  const text = useStrings().reportListControls;
  const set = (patch: Partial<ReportListFilter>) => onChange({ ...filter, ...patch });
  return (
    <FilterPanel
      sectionKey={sectionKey} layout="top" matching={matching} total={total} search={filter.search}
      onSearchChange={(search) => set({ search })} searchPlaceholder={text.searchPlaceholder} searchAriaLabel={text.searchLabel}
    >
      {kinds && (
        <FilterField label={text.kind}>
          <select className="input" value={filter.kind} onChange={(e) => set({ kind: e.target.value })}>
            <option value={FILTER_ALL}>{text.any}</option>
            {kinds.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
          </select>
        </FilterField>
      )}
      {folders.length > 0 && (
        <FilterField label={text.folder}>
          <select className="input" value={filter.folder} onChange={(e) => set({ folder: e.target.value })}>
            <option value={FILTER_ALL}>{text.any}</option>
            {folders.map((path) => <option key={path} value={path}>{path}</option>)}
          </select>
        </FilterField>
      )}
      {showSource && (
        <FilterField label={text.source}>
          <select className="input" value={filter.source} onChange={(e) => set({ source: e.target.value as ReportListSource })}>
            <option value="all">{text.any}</option>
            <option value="own">{text.sourceOwn}</option>
            <option value="shared">{text.sourceShared}</option>
          </select>
        </FilterField>
      )}
    </FilterPanel>
  );
}
