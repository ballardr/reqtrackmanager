/**
 * Module: components/SplitButtonTrigger
 *
 * A split button: clicking the main control performs the one common action immediately; a small adjacent chevron
 * reveals a menu of less-common alternatives, so the common case never stops at a menu. See
 * `docs/ux-style-guide.md`, "Pattern: split-button trigger". Generic over any primary action with one dominant case
 * plus a few alternatives.
 *
 * Design decisions:
 * - The alternatives are the shared `ActionMenuList` (text rows, never buttons) in a `Popover`, which supplies the
 *   positioning and outside-click/Escape closing; it is anchored to the chevron so the menu opens beside the control
 *   that revealed it.
 * - The chevron reveals on click, not hover: hover has no touchscreen
 *   equivalent, and every other disclosure in the app (`CollapsibleSection`, `Popover`) opens on click.
 */
import { ChevronDown } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { ActionMenuList } from "./ActionMenu";
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
        <Popover anchorRef={chevronRef} fit menu title={menuTitle} onClose={() => setMenuOpen(false)}>
          <ActionMenuList
            label={menuTitle}
            items={alternatives.map((alt, i) => ({ key: String(i), label: alt.label, onSelect: alt.onSelect }))}
            onSelect={() => setMenuOpen(false)}
          />
        </Popover>
      )}
    </div>
  );
}
