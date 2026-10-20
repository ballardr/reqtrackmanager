/**
 * Module: components/FormGrid
 *
 * The grid every form and detail page lays its fields out in (docs/ux-style-guide.md, "Pattern:
 * compact forms and add-on-demand"): short fields (a channel and a date, a checkbox and a date) sit
 * side by side in equal columns, and wrap to a single column when the space is narrow. A long field (a
 * text area, a title) spans the whole row with `FormGridFull`. Fields that are not in a pair still
 * belong in the grid, so the page keeps one left edge and one rhythm.
 */
import type { ReactNode } from "react";

import { t } from "../i18n/strings";

const strings = t();

/**
 * Lays the fields out and, when any of them is required, says what the `*` means. The legend is always
 * rendered and CSS shows it only while a `.field-required` mark is inside (`.form-grid-wrap:has(...)`),
 * so a form with no required field shows no legend.
 *
 * @param minColumn The narrowest a column may get before the grid drops a column (a CSS length): the
 *   default fits three short fields on a wide page; use `18rem` for two columns in a dialog.
 */
export function FormGrid({ children, minColumn }: { children: ReactNode; minColumn?: string }) {
  return (
    <div className="form-grid-wrap">
      <div className="form-grid" style={minColumn ? ({ "--form-grid-min": minColumn } as React.CSSProperties) : undefined}>
        {children}
      </div>
      <p className="form-required-legend text-muted">{strings.common.requiredLegend}</p>
    </div>
  );
}

/** A field that takes the full width of its `FormGrid` row. */
export function FormGridFull({ children }: { children: ReactNode }) {
  return <div className="form-grid__full">{children}</div>;
}
