import { useRef, type KeyboardEvent } from "react";

export interface TabDef<K extends string> {
  key: K;
  label: string;
}

/**
 * A shared, accessible horizontal tab bar — WAI-ARIA APG "Tabs" pattern
 * with automatic activation (arrow keys both move focus and switch the
 * active tab, matching how a mouse click already does). Replaces three
 * byte-for-byte-identical hand-rolled tab bars (`ProjectAdminPage`,
 * `ServerManagementPage`, `PreferencesPage`) that had neither
 * `role="tablist"`/`"tab"` nor keyboard navigation beyond plain Tab-through
 * (2026-08 UX audit, style guide Principle 4 — one component per pattern).
 *
 * Renders only the tab strip. Pair each panel's own wrapper element with
 * `tabPanelProps(idPrefix, key)` so the tablist/tabpanel relationship
 * (`aria-controls`/`aria-labelledby`) is actually wired up, not just
 * visual — `idPrefix` must be the same stable string passed to both.
 */
export function Tabs<K extends string>({
  idPrefix,
  tabs,
  active,
  onChange,
}: {
  idPrefix: string;
  tabs: TabDef<K>[];
  active: K;
  onChange: (key: K) => void;
}) {
  // Every tab button is always rendered (only its panel is conditional),
  // so the target of an arrow-key move already exists in the DOM — a
  // direct ref-array focus() call here is synchronous and immediate,
  // unlike focusing by id after the next render/paint.
  const buttonRefs = useRef<(HTMLButtonElement | null)[]>([]);

  function handleKeyDown(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    let nextIndex: number | null = null;
    if (e.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
    else if (e.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") nextIndex = 0;
    else if (e.key === "End") nextIndex = tabs.length - 1;
    if (nextIndex === null) return;
    e.preventDefault();
    onChange(tabs[nextIndex].key);
    buttonRefs.current[nextIndex]?.focus();
  }

  return (
    <div className="row" role="tablist" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
      {tabs.map((tb, i) => (
        <button
          key={tb.key}
          ref={(el) => {
            buttonRefs.current[i] = el;
          }}
          id={tabId(idPrefix, tb.key)}
          type="button"
          role="tab"
          aria-selected={active === tb.key}
          aria-controls={panelId(idPrefix, tb.key)}
          tabIndex={active === tb.key ? 0 : -1}
          className={`btn ${active === tb.key ? "btn-primary" : ""}`}
          onClick={() => onChange(tb.key)}
          onKeyDown={(e) => handleKeyDown(e, i)}
        >
          {tb.label}
        </button>
      ))}
    </div>
  );
}

/** Spread onto each tab panel's own wrapper element — the other half of
 * the `Tabs`/`tabPanelProps` pair, sharing the same `idPrefix`. */
export function tabPanelProps(idPrefix: string, key: string) {
  return {
    id: panelId(idPrefix, key),
    role: "tabpanel" as const,
    "aria-labelledby": tabId(idPrefix, key),
    tabIndex: 0,
  };
}

function tabId(idPrefix: string, key: string): string {
  return `${idPrefix}-tab-${key}`;
}

function panelId(idPrefix: string, key: string): string {
  return `${idPrefix}-panel-${key}`;
}
