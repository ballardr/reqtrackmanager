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

  return (
    <div className={variant === "card" ? "card stack" : "stack"}>
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="row"
        style={{
          justifyContent: "space-between",
          background: "none",
          border: "none",
          padding: 0,
          margin: 0,
          cursor: "pointer",
          width: "100%",
          textAlign: "left",
          color: "inherit",
        }}
        aria-expanded={!collapsed}
        // Disambiguates this toggle's accessible name from any same-named
        // control inside its own content (e.g. a "Change password" section
        // containing a "Change password" submit button) — both for
        // assistive tech and for test locators that query by role + name.
        aria-label={typeof title === "string" ? `${title} section` : undefined}
      >
        {variant === "card" ? (
          <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{title}</h2>
        ) : (
          <strong>{title}</strong>
        )}
        {collapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
      </button>
      {!collapsed && children}
    </div>
  );
}
