/**
 * Module: components/SplitButtonTrigger
 *
 * A true split button: clicking the main control performs the one common
 * action immediately; a small adjacent chevron reveals a menu of less-common
 * alternatives, without the common case ever stopping at a menu first. See
 * `docs/ux-style-guide.md`'s "Pattern: split-button trigger" (roadmap item
 * 505) and `docs/ux-audit-2026-08.md`'s "The 'New Requirement' trigger
 * doesn't match the requested split-button interaction" — this replaces
 * `RequirementsPage.tsx`'s previous shape, where the *whole* button opened a
 * `Popover` offering "Add one"/"Import from CSV", making every click
 * (including the common "add one" case) stop at a menu first.
 *
 * Design/implementation notes:
 * - The alternatives menu shares `Popover`'s existing positioning and
 *   outside-click/Escape-close logic (anchored to the chevron, not the main
 *   button, so the menu opens beside the control that revealed it) — per
 *   the style guide's own instruction to build this "sharing `Popover`'s
 *   existing positioning/outside-click-close logic," not a second
 *   implementation of the same behaviour.
 * - The style guide describes the reveal affordance as "a chevron, or
 *   hovering the control" — this component uses click-to-reveal on the
 *   chevron specifically, not hover. Judgment call, recorded in
 *   `docs/decisions.md`: hover has no equivalent on a touchscreen (this
 *   app's own mobile-viewport support, U-P-02, rules it out as the *only*
 *   path to the alternative action) and every other disclosure affordance
 *   in the app already opens on click (`CollapsibleSection`, `Popover`
 *   itself) — click-to-reveal keeps this component consistent with that
 *   existing convention and reliably testable, rather than introducing the
 *   app's first hover-triggered interactive menu.
 * - Not specific to "New Requirement": generic over any primary action with
 *   one dominant case plus a small number of alternatives, per the style
 *   guide's own note that the same shape applies "anywhere else a primary
 *   action currently forces a menu stop for its own most common case."
 */
import { ChevronDown } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { Popover } from "./Popover";

export interface SplitButtonAlternative {
  /** Visible label for this alternative, shown as a row in the revealed menu. */
  label: ReactNode;
  onSelect: () => void;
}

export function SplitButtonTrigger({
  icon,
  label,
  onDefaultAction,
  menuTitle,
  moreOptionsLabel,
  alternatives,
  className = "btn btn-primary",
  disabled,
}: {
  /** Icon shown before `label` on the primary (left) button — purely
   * decorative, so it isn't repeated in the accessible name. */
  icon?: ReactNode;
  /** Visible label and accessible name of the primary button. */
  label: ReactNode;
  /** Fires immediately on a plain click of the primary button — the
   * common-case action, performed with no intermediate menu. */
  onDefaultAction: () => void;
  /** `aria-label`/`Popover` title for the revealed alternatives list. */
  menuTitle: string;
  /** Accessible name for the chevron button that reveals `alternatives`. */
  moreOptionsLabel: string;
  alternatives: SplitButtonAlternative[];
  /** Shared by both halves of the split button, matching whatever the
   * equivalent single button would have used (e.g. `"btn btn-primary"`). */
  className?: string;
  disabled?: boolean;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const chevronRef = useRef<HTMLButtonElement>(null);

  return (
    <div className="split-button">
      <button type="button" className={className} onClick={onDefaultAction} disabled={disabled}>
        {icon} {label}
      </button>
      <button
        ref={chevronRef}
        type="button"
        className={className}
        aria-label={moreOptionsLabel}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        disabled={disabled}
        onClick={() => setMenuOpen((v) => !v)}
      >
        <ChevronDown size={14} />
      </button>
      {menuOpen && (
        <Popover anchorRef={chevronRef} title={menuTitle} onClose={() => setMenuOpen(false)}>
          <div className="stack" style={{ gap: "0.25rem", minWidth: 180 }}>
            {alternatives.map((alt, i) => (
              <button
                key={i}
                type="button"
                className="btn"
                style={{ justifyContent: "flex-start" }}
                onClick={() => {
                  setMenuOpen(false);
                  alt.onSelect();
                }}
              >
                {alt.label}
              </button>
            ))}
          </div>
        </Popover>
      )}
    </div>
  );
}
