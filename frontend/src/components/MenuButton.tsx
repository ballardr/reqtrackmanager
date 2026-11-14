/**
 * Module: components/MenuButton
 *
 * A labelled button with a chevron ("New ▾") that opens a short menu of choices — the shape for one
 * primary action that comes in several kinds, such as creating a Persona, Stakeholder or Need from one
 * list. It is `ActionMenu`'s labelled sibling: the same `Popover` and the same `role="menu"` list
 * (`ActionMenuList`), but a visible word instead of a kebab, because the choice is the point of the
 * button and not a hidden extra (docs/ux-style-guide.md, "Pattern: action menu"). Help for the menu is a tooltip on
 * the trigger (`help`), never a `(?)` beside it ("Pattern: help on interactive elements").
 */
import { ChevronDown } from "lucide-react";
import { useId, useRef, useState, type ReactNode } from "react";

import { ActionMenuList, type ActionMenuItem } from "./ActionMenu";
import { Popover } from "./Popover";
import { Tooltip } from "./Tooltip";

/**
 * @param label - The button's text and accessible name (e.g. "New").
 * @param items - The choices, in display order; choosing one closes the menu, then calls its `onSelect`.
 * @param primary - Gives the button the primary style (the page's main action).
 * @param disabled - Disables the button.
 * @param menuLabel - The menu's accessible name; defaults to `label`.
 * @param help - What the menu is for, one line per choice where they need explaining; the trigger's tooltip.
 * @param size - `md` (default) at page or panel level; `sm` inside a group of small buttons such as a diagram editor's
 *   toolbar, so the trigger matches its neighbours' height (docs/ux-style-guide.md, "Pattern: button sizes").
 */
export function MenuButton({
  label,
  items,
  primary,
  disabled,
  menuLabel,
  help,
  size = "md",
}: {
  label: ReactNode;
  items: ActionMenuItem[];
  primary?: boolean;
  disabled?: boolean;
  menuLabel?: string;
  help?: string;
  size?: "md" | "sm";
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const name = menuLabel ?? (typeof label === "string" ? label : "Menu");
  const bubbleId = useId();

  const trigger = (
    <button
      ref={triggerRef}
      type="button"
      className={`btn${primary ? " btn-primary" : ""}${size === "sm" ? " btn-sm" : ""}`}
      aria-haspopup="menu"
      aria-expanded={open}
      aria-describedby={help ? bubbleId : undefined}
      disabled={disabled}
      onClick={() => setOpen((o) => !o)}
    >
      {label}
      <ChevronDown aria-hidden="true" />
    </button>
  );

  return (
    <>
      {help ? <Tooltip label={help} wrap bubbleId={bubbleId}>{trigger}</Tooltip> : trigger}
      {open && (
        <Popover anchorRef={triggerRef} fit title={name} onClose={() => setOpen(false)}>
          <ActionMenuList label={name} items={items} onSelect={() => setOpen(false)} />
        </Popover>
      )}
    </>
  );
}
