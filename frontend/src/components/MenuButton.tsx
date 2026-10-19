/**
 * Module: components/MenuButton
 *
 * A labelled button with a chevron ("New ▾") that opens a short menu of choices — the shape for one
 * primary action that comes in several kinds, such as creating a Persona, Stakeholder or Need from one
 * list. It is `ActionMenu`'s labelled sibling: the same `Popover` and the same `role="menu"` list
 * (`ActionMenuList`), but a visible word instead of a kebab, because the choice is the point of the
 * button and not a hidden extra (docs/ux-style-guide.md, "Pattern: action menu").
 */
import { ChevronDown } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { ActionMenuList, type ActionMenuItem } from "./ActionMenu";
import { Popover } from "./Popover";

/**
 * @param label - The button's text and accessible name (e.g. "New").
 * @param items - The choices, in display order; choosing one closes the menu, then calls its `onSelect`.
 * @param primary - Gives the button the primary style (the page's main action).
 * @param disabled - Disables the button.
 * @param menuLabel - The menu's accessible name; defaults to `label`.
 */
export function MenuButton({
  label,
  items,
  primary,
  disabled,
  menuLabel,
}: {
  label: ReactNode;
  items: ActionMenuItem[];
  primary?: boolean;
  disabled?: boolean;
  menuLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const name = menuLabel ?? (typeof label === "string" ? label : "Menu");

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={primary ? "btn btn-primary" : "btn"}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
      >
        {label}
        <ChevronDown aria-hidden="true" />
      </button>
      {open && (
        <Popover anchorRef={triggerRef} title={name} onClose={() => setOpen(false)}>
          <ActionMenuList label={name} items={items} onSelect={() => setOpen(false)} />
        </Popover>
      )}
    </>
  );
}
