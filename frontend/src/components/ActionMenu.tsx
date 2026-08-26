/**
 * Module: components/ActionMenu
 *
 * A small kebab ("more actions") trigger that reveals a short menu of
 * related, non-primary actions — the "one door" shape style guide
 * Principle 11 already applies to grouped downloads, extended here to any
 * pair (or small group) of secondary actions that would otherwise sit on
 * screen together as separate, permanently-visible buttons competing for
 * the same row. See `docs/ux-style-guide.md`'s "Pattern: action menu" and
 * `docs/ux-audit-2026-08.md`'s "Org Admin: Users/Groups, org-level
 * actions..." section — first call site is `OrgAdminPage.tsx`'s Overview
 * group, combining "Rename" and "Export {org} bundle" behind one trigger
 * instead of two adjacent buttons plus an always-visible rename input.
 *
 * Design/implementation notes:
 * - Reuses `Popover` as the anchored, positioned, focus-trapped/restored
 *   container (`dialogA11y.ts`) rather than reinventing anchoring —
 *   the same reuse `SplitButtonTrigger` already makes for its own revealed
 *   alternatives list.
 * - `role="menu"` on the menu container and `role="menuitem"` on each
 *   action, per the roadmap item's own ask — `Popover`'s root keeps its
 *   existing `role="dialog"`/`aria-label`, so this nests a real ARIA menu
 *   inside it rather than changing `Popover` itself, which other callers
 *   (that aren't menus at all, e.g. "New group"'s create form) shouldn't
 *   be forced to inherit menu semantics from.
 * - Each item is a real, individually focusable `<button>`, so Tab/Shift+Tab
 *   already moves between them and Escape/outside-click already closes the
 *   menu (both via `Popover`'s shared `dialogA11y` hook) — this does not
 *   implement the full WAI-ARIA menu widget's arrow-key roving-tabindex
 *   pattern (`ResourceMenu`/`Tabs` do that for their own, larger surfaces);
 *   for a menu this short (2-3 items), Tab-based keyboard access plus a
 *   real `role="menu"`/`"menuitem"` pair for assistive tech was judged
 *   proportionate rather than under-built — see `docs/decisions.md` if a
 *   future call site needs more items and arrow-key nav becomes worth it.
 */
import type { ReactNode } from "react";
import { MoreVertical } from "lucide-react";
import { useRef, useState } from "react";

import { Popover } from "./Popover";

export interface ActionMenuItem {
  /** Visible label and accessible name for this menu item. */
  label: ReactNode;
  /** Decorative icon shown before `label` — not repeated in the accessible name. */
  icon?: ReactNode;
  onSelect: () => void;
}

/**
 * Renders a `MoreVertical` kebab button; clicking it opens a `Popover`
 * (anchored to the kebab) containing `items` as `role="menuitem"` buttons.
 * Selecting an item closes the menu and then calls its own `onSelect` —
 * callers don't need to close the menu themselves.
 *
 * @param triggerLabel - Accessible name (`aria-label`/`title`) for the
 *   kebab trigger itself, and the menu's own `aria-label`/`Popover` title.
 *   Should name what the menu acts on (e.g. `` `${org.name} actions` ``),
 *   not a bare "More actions" — Principle 8 (every interactive control has
 *   a real name), especially relevant if more than one `ActionMenu` can
 *   ever appear on the same page.
 * @param items - The menu's rows, in display order.
 * @param disabled - Disables the trigger itself (e.g. while one of the
 *   menu's own actions, such as an export, is already in flight).
 */
export function ActionMenu({
  triggerLabel,
  items,
  disabled,
}: {
  triggerLabel: string;
  items: ActionMenuItem[];
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="btn"
        aria-label={triggerLabel}
        title={triggerLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
      >
        <MoreVertical size={14} />
      </button>
      {open && (
        <Popover anchorRef={triggerRef} title={triggerLabel} onClose={() => setOpen(false)}>
          <div role="menu" aria-label={triggerLabel} className="stack" style={{ gap: "0.15rem", minWidth: 180 }}>
            {items.map((item, i) => (
              <button
                key={i}
                type="button"
                role="menuitem"
                className="btn"
                style={{ justifyContent: "flex-start" }}
                onClick={() => {
                  setOpen(false);
                  item.onSelect();
                }}
              >
                {item.icon} {item.label}
              </button>
            ))}
          </div>
        </Popover>
      )}
    </>
  );
}
