/**
 * Module: components/AddPopoverButton
 *
 * The "add one" affordance for a field or list that is usually already filled in: a small (+) icon button that
 * opens a `Popover` holding the add form (the caller's `children`, handed a `close` callback to call once the add
 * succeeds), so a detail page with many linkable lists stays short (docs/ux-style-guide.md, "Pattern: compact
 * forms and add-on-demand").
 *
 * The popover opens to the right of the button (below it when there is no room). One or two fields fit a
 * `Popover`; a control that itself opens a popover (a `TreeSelect`) or a form of three or more fields belongs in
 * a `Modal`, because Popovers do not nest.
 */
import { Plus } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { Popover } from "./Popover";
import { Tooltip } from "./Tooltip";

/**
 * @param label Accessible name of the button and title of the popover, e.g. "Add to Participants".
 * @param children The add form; called with `close`, which dismisses the popover.
 * @param disabled Disables the button, e.g. while there is nothing left to add.
 * @param icon Replaces the (+) icon, e.g. a pencil when the control changes an existing value.
 * @param text A word shown beside the icon ("+ Field"), for a button that must say what it adds; the accessible
 *   name stays `label`.
 * @param size `sm` (default) beside a heading or value in a page's body; `md` when it sits in a group
 *   of default-size buttons (a panel header), so neighbours match (style guide, "Pattern: button sizes").
 */
export function AddPopoverButton({
  label,
  children,
  disabled,
  icon: Icon = Plus,
  size = "sm",
  text,
}: {
  label: string;
  children: (close: () => void) => ReactNode;
  disabled?: boolean;
  icon?: typeof Plus;
  size?: "sm" | "md";
  text?: string;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  return (
    <>
      <Tooltip label={label} disabled={open || !!text}>
        <button
          ref={triggerRef}
          type="button"
          className={`btn${size === "sm" ? " btn-sm" : ""}${text ? "" : " btn-icon"}`}
          aria-label={label}
          aria-haspopup="dialog"
          aria-expanded={open}
          disabled={disabled}
          onClick={() => setOpen((o) => !o)}
        >
          <Icon size={14} aria-hidden="true" />
          {text && <span style={{ marginLeft: "var(--space-1)" }}>{text}</span>}
        </button>
      </Tooltip>
      {open && (
        <Popover anchorRef={triggerRef} title={label} placement="side" onClose={() => setOpen(false)}>
          {children(() => setOpen(false))}
        </Popover>
      )}
    </>
  );
}
