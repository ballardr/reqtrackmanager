import type { ReactNode } from "react";

import { useNarrowViewport } from "../hooks/useNarrowViewport";
import { t } from "../i18n/strings";
import { CollapsibleSection } from "./CollapsibleSection";
import { ResultCount } from "./ResultCount";

const strings = t();

// Matches `.side-grid`'s own mobile collapse breakpoint (theme.css,
// `@media (max-width: 860px)`) — the filter body's own collapse and the
// surrounding two-column-to-one-column layout collapse should agree on
// where "mobile" starts, rather than the two disagreeing at some widths.
const MOBILE_BREAKPOINT_PX = 860;

/**
 * Right-side filter sidebar shell (mock's Search/Status/Category/Filters
 * panel), restructured (2026-08 UX audit roadmap: persistent "showing X of
 * Y" result count) into a header + collapsible body:
 *
 *  - Header (always rendered, never collapses): when the caller passes
 *    `total` (the unfiltered mandatory-scope count), a `ResultCount` —
 *    `matching` (the current filtered/searched count) defaults to `total`
 *    itself when omitted, i.e. plain "N total" with no distinct filtered
 *    figure. Callers with no comparable "total" concept at all (a plain,
 *    unpaginated filter sidebar) omit `total` and get no `ResultCount`,
 *    unchanged from before this header existed. Also, when the caller
 *    passes `onSearchChange`, a free-text search `<input>`.
 *  - Body (`children`, the dropdown/checkbox filter controls): on desktop/
 *    wide viewports renders as if always expanded, with no visible toggle
 *    friction; below `MOBILE_BREAKPOINT_PX` it defaults to collapsed with a
 *    toggle to expand, via the existing `CollapsibleSection` accordion
 *    (style guide Principle 1, "Accordion (CollapsibleSection)") rather
 *    than a new disclosure widget.
 *
 * `sectionKey` must be unique per page — it's `CollapsibleSection`'s own
 * per-user, cross-device persisted collapsed/expanded key, so two pages
 * sharing one key would also share the same stored preference.
 */
export function FilterPanel({
  sectionKey,
  matching,
  total,
  search,
  onSearchChange,
  searchPlaceholder,
  searchAriaLabel,
  children,
}: {
  sectionKey: string;
  matching?: number;
  total?: number;
  search?: string;
  onSearchChange?: (value: string) => void;
  searchPlaceholder?: string;
  searchAriaLabel?: string;
  children: ReactNode;
}) {
  const isNarrow = useNarrowViewport(MOBILE_BREAKPOINT_PX);
  return (
    <div className="card stack filter-panel" style={{ alignSelf: "flex-start", minWidth: 220 }}>
      <div className="stack" style={{ gap: "0.5rem" }}>
        {total !== undefined && <ResultCount matching={matching ?? total} total={total} />}
        {onSearchChange && (
          <input
            className="input"
            placeholder={searchPlaceholder}
            aria-label={searchAriaLabel ?? searchPlaceholder}
            value={search ?? ""}
            onChange={(e) => onSearchChange(e.target.value)}
          />
        )}
      </div>
      {isNarrow ? (
        <CollapsibleSection sectionKey={sectionKey} title={strings.common.filters} defaultCollapsed>
          <div className="stack">{children}</div>
        </CollapsibleSection>
      ) : (
        <div className="stack">
          <h2 style={{ margin: 0, fontSize: "1rem" }}>{strings.common.filters}</h2>
          {children}
        </div>
      )}
    </div>
  );
}

export function FilterField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="stack" style={{ gap: "0.25rem" }}>
      <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>
        {label}
      </span>
      {children}
    </label>
  );
}

export function FilterCheckbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="row" style={{ gap: "0.4rem" }}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}
