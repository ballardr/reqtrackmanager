/**
 * Module: components/DialogHeader
 *
 * The header every `Modal` and `SidePanel` shares: the title, the form's actions and the close button
 * in one pinned row, with the save error beneath it (docs/ux-style-guide.md, "Pattern: form header").
 *
 * Responsibilities:
 * - `DialogFrame` lays a dialog out as a fixed header over a scrolling body, so Save stays reachable on
 *   a long form.
 * - It exposes the header's two mount points (actions, error) through `dialogSlots.ts` to
 *   `FormActions`, which portals into them. A form therefore keeps rendering `FormActions` where it
 *   always did, and the buttons appear in the header; React events, context and closures cross a portal
 *   unchanged, so no form needs to know.
 * - A `Popover` provides `null` slots, so an inline form inside a popover keeps its own buttons.
 *
 * Dependencies: lucide-react (close icon), i18n strings.
 */
import { X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { t } from "../i18n/strings";
import { DialogSlotContext } from "./dialogSlots";

const strings = t();

/**
 * The inside of a dialog card: pinned header (title, actions, close, save error) over a scrolling body.
 * The caller supplies the outer card and its size; this fills it.
 *
 * @param title The dialog title, shown as the heading.
 * @param onClose Called by the close (x) button.
 * @param children The dialog body; it scrolls, the header does not.
 */
export function DialogFrame({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const [actions, setActions] = useState<HTMLElement | null>(null);
  const [error, setError] = useState<HTMLElement | null>(null);

  return (
    <DialogSlotContext.Provider value={{ actions, error }}>
      <div className="dialog-header">
        <div className="dialog-header-row">
          <h2 className="dialog-title">{title}</h2>
          <div className="dialog-header-controls">
            <div ref={setActions} className="dialog-header-actions" />
            <button className="btn" onClick={onClose} aria-label={strings.common.close} title={strings.common.close}>
              <X />
            </button>
          </div>
        </div>
        <div ref={setError} />
      </div>
      <div className="dialog-body stack">{children}</div>
    </DialogSlotContext.Provider>
  );
}
