/**
 * Module: modules/architecture/SymbolGallery
 *
 * The body of the symbol picker's Gallery view: a scrolling grid of tiles that show each drawing, with a
 * "None" tile first (the default the empty choice stands for) and the current choice marked. The grid is one radio
 * group: arrow keys move between tiles, Enter or Space chooses, and the roving tab stop keeps one tile in the Tab order. A
 * tile reads its drawing only when it scrolls into view, so a library of hundreds opens without hundreds of requests
 * at once. A tile is a plain bordered control, not a menu row.
 */
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { SymbolImage } from "./SymbolImage";
import type { ArchitectureSymbol } from "./types";

const TILE_SIZE = 44;

/**
 * Draws one symbol, requesting its content only once the tile is on screen.
 *
 * @param src The API path of the symbol's content. The tile's own name is the accessible name, so the image is decorative.
 * @param size The width and height in pixels.
 */
export function LazySymbolImage({ src, size = TILE_SIZE }: { src: string; size?: number }) {
  const holder = useRef<HTMLSpanElement>(null);
  // Without IntersectionObserver (an old browser) every tile reads at once, as the List view's preview does.
  const [seen, setSeen] = useState(() => typeof IntersectionObserver === "undefined");
  useEffect(() => {
    if (seen || !holder.current) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setSeen(true);
        observer.disconnect();
      }
    });
    observer.observe(holder.current);
    return () => observer.disconnect();
  }, [seen]);
  return (
    <span ref={holder} style={{ display: "inline-flex", width: size, height: size, alignItems: "center", justifyContent: "center" }}>
      {seen ? <SymbolImage src={src} alt="" size={size} /> : null}
    </span>
  );
}

/** One tile of the grid (the None tile or a symbol), a radio of the group. */
function Tile({
  name, chosen, tabbable, onChoose, children, tileRef, onKeyDown,
}: {
  name: string;
  chosen: boolean;
  tabbable: boolean;
  onChoose: () => void;
  children: ReactNode;
  tileRef: (element: HTMLButtonElement | null) => void;
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
}) {
  return (
    <button
      type="button" role="radio" aria-checked={chosen} aria-label={name} ref={tileRef} tabIndex={tabbable ? 0 : -1}
      onClick={onChoose} onKeyDown={onKeyDown}
      style={{
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-start", gap: "var(--space-1)",
        padding: "var(--space-2)", background: chosen ? "var(--color-surface-alt)" : "var(--color-surface)",
        color: "var(--color-text)", cursor: "pointer", minWidth: 0, font: "inherit",
        border: `${chosen ? 2 : 1}px solid ${chosen ? "var(--color-accent)" : "var(--color-border)"}`, borderRadius: "var(--radius-md, 6px)",
      }}
    >
      {children}
      <span aria-hidden="true" style={{ fontSize: "0.75rem", textAlign: "center", overflowWrap: "anywhere", lineHeight: 1.2 }}>{name}</span>
    </button>
  );
}

/**
 * @param symbols The symbols shown (already narrowed by the picker's filter).
 * @param total How many symbols the library holds, to tell an empty library from a filter with no match.
 * @param value The chosen symbol's id, or `null` for none.
 * @param onChoose Called with the chosen id, or `null` for the None tile.
 * @param urlFor The API path of a symbol's content.
 * @param emptyLabel The None tile's text (what the default is).
 */
export function SymbolGallery({
  symbols, total, value, onChoose, urlFor, emptyLabel,
}: {
  symbols: ArchitectureSymbol[];
  total: number;
  value: string | null;
  onChoose: (next: string | null) => void;
  urlFor: (symbolId: string) => string;
  emptyLabel: string;
}) {
  const tiles = useRef<(HTMLButtonElement | null)[]>([]);
  // The tile in the Tab order: the chosen one when shown, else the first (the None tile).
  const tabIndex = value === null ? 0 : symbols.findIndex((s) => s.id === value) + 1;
  const count = symbols.length + 1;

  function move(from: number, event: KeyboardEvent<HTMLButtonElement>) {
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    const target = event.key === "Home" ? 0 : event.key === "End" ? count - 1 : step === 0 ? null : (from + step + count) % count;
    if (target === null) return;
    event.preventDefault();
    tiles.current[target]?.focus();
  }

  return (
    <div className="stack" style={{ gap: "var(--space-2)", minWidth: 0 }}>
      <div
        role="radiogroup" aria-label="Symbols" className="scroll-region"
        style={{
          display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(5.5rem, 1fr))", gap: "var(--space-2)",
          maxHeight: "min(20rem, 50vh)", padding: "2px",
        }}
      >
        <Tile
          name={emptyLabel} chosen={value === null} tabbable={tabIndex === 0} onChoose={() => onChoose(null)}
          tileRef={(el) => { tiles.current[0] = el; }} onKeyDown={(e) => move(0, e)}
        >
          <span aria-hidden="true" className="text-muted" style={{ display: "inline-flex", width: TILE_SIZE, height: TILE_SIZE, alignItems: "center", justifyContent: "center" }}>—</span>
        </Tile>
        {symbols.map((symbol, index) => (
          <Tile
            key={symbol.id} name={symbol.name} chosen={symbol.id === value} tabbable={tabIndex === index + 1}
            onChoose={() => onChoose(symbol.id)} tileRef={(el) => { tiles.current[index + 1] = el; }} onKeyDown={(e) => move(index + 1, e)}
          >
            <LazySymbolImage src={urlFor(symbol.id)} />
          </Tile>
        ))}
      </div>
      {total === 0 && <div className="text-muted">The symbol library is empty.</div>}
      {total > 0 && symbols.length === 0 && <div className="text-muted">No symbols match.</div>}
    </div>
  );
}
