import { ChevronDown, ChevronUp } from "lucide-react";
import { useId, type ReactNode } from "react";

import { useUiPreference } from "../hooks/useUiPreference";
import { Badge } from "./Badge";

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
 *
 * A closed section can say what it holds: `summary` is a pill on the bar ("2 changed"), `marked` adds an accent
 * border so a bar holding non-default content is not read as empty (text plus border, never colour alone), and
 * `forceOpen` keeps the section open (and its toggle inert) while it holds something the person must see, with the
 * pill turning to the danger tone.
 */
export function CollapsibleSection({
  sectionKey,
  title,
  variant = "card",
  defaultCollapsed = false,
  summary,
  marked = false,
  forceOpen = false,
  children,
}: {
  sectionKey: string;
  title: ReactNode;
  variant?: "card" | "plain";
  defaultCollapsed?: boolean;
  /** Short text for a pill on the bar (what the section holds); absent: no pill. */
  summary?: string;
  /** Accent border on the bar, for a section that holds non-default content. */
  marked?: boolean;
  /** Keep the section open and its toggle inert (a problem inside it); the pill takes the danger tone. */
  forceOpen?: boolean;
  children: ReactNode;
}) {
  const [stored, setCollapsed] = useUiPreference<boolean>(`section_collapsed:${sectionKey}`, defaultCollapsed);
  const collapsed = forceOpen ? false : stored;
  const toggle = () => { if (!forceOpen) setCollapsed(!stored); };
  const contentId = useId();
  const pillId = useId();
  // Disambiguates this toggle's accessible name from any same-named control
  // inside its own content (e.g. a "Change password" section containing a
  // "Change password" submit button) — both for assistive tech and for test
  // locators that query by role + name.
  const label = typeof title === "string" ? `${title} section` : undefined;

  const heading =
    variant === "card" ? (
      <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{title}</h2>
    ) : (
      <strong>{title}</strong>
    );
  const header = summary ? (
    <span className="row" style={{ gap: "var(--space-2)" }}>
      {heading}
      <Badge id={pillId} tone={forceOpen ? "danger" : marked ? "accent" : "muted"}>{summary}</Badge>
    </span>
  ) : heading;
  const barClass = marked && !forceOpen ? " collapsible-bar--marked" : "";

  if (collapsed) {
    // The whole collapsed bar is the click target (not just the title/arrow
    // text) — for `variant="card"` that means the entire card, padding
    // included, since a collapsed section visually reads as one solid bar.
    return (
      <div
        className={`${variant === "card" ? "card row" : "row"}${barClass}`}
        style={{ justifyContent: "space-between", cursor: "pointer" }}
        aria-describedby={summary ? pillId : undefined}
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
        aria-controls={contentId}
        aria-disabled={forceOpen || undefined}
        aria-describedby={summary ? pillId : undefined}
        aria-label={label}
      >
        {header}
        <ChevronUp size={16} />
      </div>
      <div id={contentId} className="stack">{children}</div>
    </div>
  );
}
