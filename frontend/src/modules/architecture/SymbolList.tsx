/**
 * Module: modules/architecture/SymbolList
 *
 * The body of the symbol picker's List view: a "None" row first (the default the empty choice stands for) and one text row
 * per symbol name, the current choice marked. The rows are one listbox: arrow keys move between them, Enter or Space
 * chooses, and the roving tab stop keeps one row in the Tab order. The rows are the shared `menu-item` text row.
 */
import { useRef, type KeyboardEvent } from "react";

import type { ArchitectureSymbol } from "./types";

/**
 * @param symbols The symbols shown (already narrowed by the picker's filter).
 * @param total How many symbols the library holds, to tell an empty library from a filter with no match.
 * @param value The chosen symbol's id, or `null` for none.
 * @param onChoose Called with the chosen id, or `null` for the None row.
 * @param emptyLabel The None row's text (what the default is).
 */
export function SymbolList({
  symbols, total, value, onChoose, emptyLabel,
}: {
  symbols: ArchitectureSymbol[];
  total: number;
  value: string | null;
  onChoose: (next: string | null) => void;
  emptyLabel: string;
}) {
  const rows = useRef<(HTMLButtonElement | null)[]>([]);
  const count = symbols.length + 1;
  // The row in the Tab order: the chosen one when shown, else the first (the None row).
  const tabIndex = value === null ? 0 : Math.max(0, symbols.findIndex((s) => s.id === value) + 1);

  function move(from: number, event: KeyboardEvent<HTMLButtonElement>) {
    const target = event.key === "Home" ? 0
      : event.key === "End" ? count - 1
        : event.key === "ArrowDown" ? (from + 1) % count
          : event.key === "ArrowUp" ? (from - 1 + count) % count : null;
    if (target === null) return;
    event.preventDefault();
    rows.current[target]?.focus();
  }

  const row = (index: number, name: string, chosen: boolean, next: string | null) => (
    <button
      key={next ?? "none"} type="button" role="option" aria-selected={chosen} className="menu-item" tabIndex={tabIndex === index ? 0 : -1}
      ref={(el) => { rows.current[index] = el; }} onClick={() => onChoose(next)} onKeyDown={(e) => move(index, e)}
    >
      {name}
    </button>
  );

  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      <div role="listbox" aria-label="Symbols" className="menu-list scroll-region" style={{ maxHeight: "min(20rem, 50vh)" }}>
        {row(0, emptyLabel, value === null, null)}
        {symbols.map((symbol, index) => row(index + 1, symbol.name, symbol.id === value, symbol.id))}
      </div>
      {total === 0 && <div className="text-muted">The symbol library is empty.</div>}
      {total > 0 && symbols.length === 0 && <div className="text-muted">No symbols match.</div>}
    </div>
  );
}
