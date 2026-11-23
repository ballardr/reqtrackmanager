import { PanelTopClose } from "lucide-react";
import { useContext, type ReactNode } from "react";

import { FilterCollapseContext } from "../context/FilterCollapseContext";

import { useNarrowViewport } from "../hooks/useNarrowViewport";
import { t } from "../i18n/strings";
import { CollapsibleSection } from "./CollapsibleSection";
import { Tooltip } from "./Tooltip";
import { ResultCount } from "./ResultCount";
import { FieldCaption } from "./FieldHelp";
import { CheckboxField } from "./FormFields";

const strings = t();

// Matches `.side-grid`'s mobile collapse breakpoint (theme.css `@media (max-width: 860px)`), so the filter body
// and the two-column layout collapse at the same width.
const MOBILE_BREAKPOINT_PX = 860;

/**
 * Filter shell: a header plus a collapsible body.
 *
 *  - Header (always rendered): with `total` (the unfiltered mandatory-scope count) a `ResultCount` (`matching`
 *    defaults to `total`); with `onSearchChange` a free-text search `<input>`.
 *  - Body (`children`): expanded on wide viewports; below `MOBILE_BREAKPOINT_PX` collapsed by default behind the
 *    `CollapsibleSection` accordion (style guide Principle 1). `children={null}` omits the body entirely.
 *
 * `layout` is the placement of the style guide's "Pattern: filter panel placement - side vs. top": `"side"`
 * (default) is a narrow (`minWidth: 220`) sidebar beside a `.side-grid` column with stacked fields; `"top"` is a
 * full-width horizontal bar above the content with no `minWidth`/`alignSelf` and no "Filters" heading, for wide,
 * many-column directories.
 *
 * In a `ListPageLayout` (`FilterCollapseContext`) the side layout's title row holds a collapse toggle (round, icon
 * only, tooltip); the layout then hides the panel and shows a "Filters" button beside the list actions.
 * `sectionKey` must be unique per page: it is `CollapsibleSection`'s persisted key.
 */
export function FilterPanel({
  sectionKey,
  matching,
  total,
  search,
  onSearchChange,
  searchPlaceholder,
  searchAriaLabel,
  layout = "side",
  children,
}: {
  sectionKey: string;
  matching?: number;
  total?: number;
  search?: string;
  onSearchChange?: (value: string) => void;
  searchPlaceholder?: string;
  searchAriaLabel?: string;
  layout?: "side" | "top";
  children: ReactNode;
}) {
  const isNarrow = useNarrowViewport(MOBILE_BREAKPOINT_PX);
  const isTop = layout === "top";
  const collapse = useContext(FilterCollapseContext);
  // With no filter fields beyond the search box (`children` is `null`) the title says "Search": a "Filters"
  // heading over an empty body reads as broken.
  const hasFilterFields = children != null;
  const body = isTop ? (
    <div className="row" style={{ gap: "var(--space-4)", rowGap: "var(--space-3)", flexWrap: "wrap", alignItems: "flex-end" }}>
      {children}
    </div>
  ) : (
    <div className="stack">{children}</div>
  );
  return (
    <div
      className={isTop ? "card stack filter-panel filter-panel-top" : "card stack filter-panel"}
      style={isTop ? undefined : { alignSelf: "flex-start", minWidth: 220 }}
    >
      {!isTop && (
        <div className="row" style={{ alignItems: "center", flexWrap: "nowrap", gap: "var(--space-4)" }}>
          <h2 style={{ margin: 0, fontSize: "1rem" }}>{hasFilterFields ? strings.common.filters : strings.common.searchTitle}</h2>
          {collapse && (
            <Tooltip label={strings.common.hideFilters} style={{ marginLeft: "auto" }}>
              <button
                type="button" className="btn btn-icon btn-sm btn-round" aria-expanded
                aria-label={strings.common.hideFilters} onClick={collapse.toggle}
              >
                <PanelTopClose />
              </button>
            </Tooltip>
          )}
        </div>
      )}
      {<div
        className={isTop ? "row" : "stack"}
        style={isTop ? { gap: "var(--space-4)", rowGap: "var(--space-3)", flexWrap: "wrap", alignItems: "center" } : { gap: "var(--space-3)" }}
      >
        {total !== undefined && <ResultCount matching={matching ?? total} total={total} />}
        {onSearchChange && (
          <input
            className="input"
            placeholder={searchPlaceholder}
            aria-label={searchAriaLabel ?? searchPlaceholder}
            value={search ?? ""}
            onChange={(e) => onSearchChange(e.target.value)}
            style={isTop ? { maxWidth: 280 } : undefined}
          />
        )}
      </div>}
      {!hasFilterFields ? null : isNarrow ? (
        <CollapsibleSection sectionKey={sectionKey} title={strings.common.filters} defaultCollapsed>
          {body}
        </CollapsibleSection>
      ) : isTop ? (
        body
      ) : (
        <div className="stack">{children}</div>
      )}
    </div>
  );
}

/**
 * One labelled control of the filter panel.
 *
 * @param label The caption.
 * @param help What the options mean, as a `(?)` tooltip after the caption (docs/ux-style-guide.md, "Pattern: explain in
 *   help, not in the layout"). With help the caption and control are siblings, not one `<label>` (a button inside a label
 *   would take its place), so the control must name itself (`aria-label`).
 * @param children The control.
 */
export function FilterField({ label, help, children }: { label: string; help?: string; children: ReactNode }) {
  if (help) {
    return (
      <div className="stack" style={{ gap: "var(--space-1)" }}>
        <FieldCaption label={label} help={help} muted />
        {children}
      </div>
    );
  }
  return (
    <label className="stack" style={{ gap: "var(--space-1)" }}>
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
  help,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Tooltip saying what ticking the box adds or removes; omitted for a self-explanatory filter. */
  help?: string;
}) {
  return help ? (
    <CheckboxField help={help} label={label} checked={checked} onChange={onChange} />
  ) : (
    <CheckboxField helpNotNeeded label={label} checked={checked} onChange={onChange} />
  );
}

