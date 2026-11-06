/**
 * Module: components/SectionOrderEditor
 *
 * The control for arranging the sections of a record page: each section on its own row with move up and move down,
 * and a reset that returns to the layer underneath (the built-in order, or a project's default). Used for a project
 * administrator's default order and for a person's own order on the page, so both read the same.
 *
 * It only edits an array of keys; where that is saved, and how it layers over another, is the caller's
 * (`utils/sectionOrder`).
 */
import { ArrowDown, ArrowUp } from "lucide-react";

import { moveSection } from "../utils/sectionOrder";
import { AlignedRows } from "./AlignedRows";

/** One arrangeable section: its key and the name shown. */
export interface SectionOption {
  key: string;
  label: string;
}

/**
 * @param sections Every section, which gives the label of each key.
 * @param order The order now (a permutation of the keys).
 * @param onChange Called with the new order after a move.
 * @param onReset Returns to the layer underneath; the button is omitted when this is not given.
 * @param resetLabel The reset button's text.
 * @param resetDisabled True while there is nothing to reset (the order is not customised).
 * @param ariaLabel Accessible name of the list.
 */
export function SectionOrderEditor({
  sections, order, onChange, onReset, resetLabel = "Reset", resetDisabled = false, ariaLabel = "Section order",
}: {
  sections: readonly SectionOption[];
  order: readonly string[];
  onChange: (next: string[]) => void;
  onReset?: () => void;
  resetLabel?: string;
  resetDisabled?: boolean;
  ariaLabel?: string;
}) {
  const label = (key: string) => sections.find((s) => s.key === key)?.label ?? key;
  return (
    <div className="stack">
      <AlignedRows
        ordered ariaLabel={ariaLabel}
        rows={order.map((key, index) => ({
          id: key,
          lead: <span className="text-muted">{index + 1}</span>,
          main: label(key),
          actions: (
            <>
              <button
                type="button" className="btn btn-sm btn-icon" title={`Move ${label(key)} up`} aria-label={`Move ${label(key)} up`}
                disabled={index === 0} onClick={() => onChange(moveSection(order, key, -1))}
              >
                <ArrowUp />
              </button>
              <button
                type="button" className="btn btn-sm btn-icon" title={`Move ${label(key)} down`} aria-label={`Move ${label(key)} down`}
                disabled={index === order.length - 1} onClick={() => onChange(moveSection(order, key, 1))}
              >
                <ArrowDown />
              </button>
            </>
          ),
        }))}
      />
      {onReset && (
        <div><button type="button" className="btn btn-sm" disabled={resetDisabled} onClick={onReset}>{resetLabel}</button></div>
      )}
    </div>
  );
}
