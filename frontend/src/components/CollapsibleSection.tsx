import { ChevronDown, ChevronUp } from "lucide-react";
import type { ReactNode } from "react";

import { useUiPreference } from "../hooks/useUiPreference";

/**
 * A section that can be collapsed to just its title, remembering the
 * choice per `sectionKey` in the user's `ui_preferences` bag (keyed
 * `section_collapsed:<sectionKey>`) so it stays collapsed/expanded across
 * visits and devices.
 *
 * `variant="card"` (default) renders its own `.card` background, for a
 * page's top-level sections. `variant="plain"` renders only the header +
 * children with no background/border, for a smaller subsection nested
 * inside a parent card (e.g. "Create" within a "Personal Access Tokens"
 * card) — nesting a full card inside a card reads as visually heavy.
 */
export function CollapsibleSection({
  sectionKey,
  title,
  variant = "card",
  defaultCollapsed = false,
  children,
}: {
  sectionKey: string;
  title: ReactNode;
  variant?: "card" | "plain";
  defaultCollapsed?: boolean;
  children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useUiPreference<boolean>(`section_collapsed:${sectionKey}`, defaultCollapsed);
  const toggle = () => setCollapsed(!collapsed);
  // Disambiguates this toggle's accessible name from any same-named control
  // inside its own content (e.g. a "Change password" section containing a
  // "Change password" submit button) — both for assistive tech and for test
  // locators that query by role + name.
  const label = typeof title === "string" ? `${title} section` : undefined;

  const header =
    variant === "card" ? (
      <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{title}</h2>
    ) : (
      <strong>{title}</strong>
    );

  if (collapsed) {
    // The whole collapsed bar is the click target (not just the title/arrow
    // text) — for `variant="card"` that means the entire card, padding
    // included, since a collapsed section visually reads as one solid bar.
    return (
      <div
        className={variant === "card" ? "card row" : "row"}
        style={{ justifyContent: "space-between", cursor: "pointer" }}
        role="button"
        tabIndex={0}
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            toggle();
          }
        }}
        aria-expanded={false}
        aria-label={label}
      >
        {header}
        <ChevronDown size={16} />
      </div>
    );
  }

  return (
    <div className={variant === "card" ? "card stack" : "stack"}>
      {/* `role="button"` on a <div>, not a real <button> — `title` is
          arbitrary ReactNode and at least one caller (PreferencesPage's 2FA
          section) nests a real interactive <button> (ToggleSwitch) inside
          it; a <button> wrapper here would make that a `<button>` inside a
          `<button>`, invalid HTML that breaks click/keyboard handling
          unpredictably. Mirrors the collapsed-state branch above, which
          already uses this same div+role pattern. */}
      <div
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            toggle();
          }
        }}
        role="button"
        tabIndex={0}
        className="row"
        style={{
          justifyContent: "space-between",
          cursor: "pointer",
          width: "100%",
          textAlign: "left",
          color: "inherit",
        }}
        aria-expanded={true}
        aria-label={label}
      >
        {header}
        <ChevronUp size={16} />
      </div>
      {children}
    </div>
  );
}
