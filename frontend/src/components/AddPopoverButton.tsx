/**
 * Module: components/AddPopoverButton
 *
 * The "add one" affordance for a field or list that is usually already filled in: a small (+)
 * icon button that opens a `Popover` holding the add form, instead of leaving the form open
 * under the list all the time. The form is the caller's (`children`), and is handed a `close`
 * callback to call once the add succeeds. It exists so a detail page with many linkable lists
 * (participants, covered Personas, outcomes, ...) stays short: each list costs one heading line
 * until someone actually adds to it (docs/ux-style-guide.md, "Pattern: compact forms and
 * add-on-demand").
 *
 * The popover opens to the right of the button (below it when there is no room), so it does not cover the
 * list the button belongs to.
 *
 * One or two fields fit a `Popover`. A control that itself opens a popover (a `TreeSelect`) or a
 * form of three or more fields belongs in a `Modal` instead, because Popovers do not nest.
 */
import { Plus } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { Popover } from "./Popover";

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
      <button
        ref={triggerRef}
        type="button"
        className={`btn${size === "sm" ? " btn-sm" : ""}${text ? "" : " btn-icon"}`}
        aria-label={label}
        title={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
      >
        <Icon size={14} aria-hidden="true" />
        {text && <span style={{ marginLeft: "var(--space-1)" }}>{text}</span>}
      </button>
      {open && (
        <Popover anchorRef={triggerRef} title={label} placement="side" onClose={() => setOpen(false)}>
          {children(() => setOpen(false))}
        </Popover>
      )}
    </>
  );
}
