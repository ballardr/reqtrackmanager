/**
 * Module: components/DetailCard
 *
 * The card a record detail page puts its content in: the record's fields under "Details", another group of them,
 * or a panel (versions, attachments, comments) under its own heading. The page header (back link, title, status
 * badges, transitions) stays on the page background (docs/ux-style-guide.md, "Pattern: detail page content").
 *
 * Cards never nest (`scripts/check_detail_cards.py`). The heading is a real `<h2>` naming the section.
 *
 * With `maxHeight` the heading stays at the top and the content scrolls inside a keyboard-reachable group named
 * "<heading> content", without scrolling the page at its ends; a short card keeps its natural height. A
 * `CardHeaderAction` rendered anywhere in the card appears on the heading's line, after `action`. A
 * `.selection-actions` row inside the scrolling region stays at the top.
 */
import { useState, type KeyboardEventHandler, type ReactNode } from "react";

import type { DetailRank } from "./detailCardOrder";
import { DetailCardActionsContext } from "./detailCardSlots";
import { FieldHelp } from "./FieldHelp";

/**
 * @param heading The card's name for assistive technology and the visible heading (default "Details").
 * @param title Visible heading text when it should say more than the card's name, e.g. the selected item (the card stays named `heading`).
 * @param help Plain-language help for a heading that names a domain term; drawn as a `(?)` after the heading.
 * @param action A control on the heading's line, e.g. an `AddPopoverButton`.
 * @param onKeyDown Hears key presses bubbling up from the card's controls (the editors' Selection cards return focus to the canvas on Escape).
 * @param rank Where the card sits on a detail page (`detailCardOrder`): `body` by default; `supporting` for versions and attachments, `discussion` for comments. Read by `DetailLayout`; it does not change how the card is drawn.
 * @param maxHeight The tallest the card may be, in pixels; the content scrolls inside when it needs more. Omit for a card that grows with its content.
 * @param children The card's content.
 */
export function DetailCard({
  heading = "Details", title, help, action, onKeyDown, maxHeight, children,
}: {
  heading?: string; title?: ReactNode; help?: string; action?: ReactNode; onKeyDown?: KeyboardEventHandler<HTMLElement>; rank?: DetailRank; maxHeight?: number; children: ReactNode;
}) {
  const [actionsSlot, setActionsSlot] = useState<HTMLElement | null>(null);
  const shown = title ?? heading;
  return (
    <DetailCardActionsContext.Provider value={actionsSlot}>
    <section
      className={maxHeight === undefined ? "card stack" : "card stack detail-card--scrolls"} aria-label={heading} onKeyDown={onKeyDown}
      style={maxHeight === undefined ? undefined : { maxHeight }}
    >
      <div className="row detail-card__head">
        {help ? (
          <div className="field-caption">
            <h2 className="detail-card__title">{shown}</h2>
            <FieldHelp label={heading} help={help} />
          </div>
        ) : (
          <h2 className="detail-card__title">{shown}</h2>
        )}
        {action}
        <span ref={setActionsSlot} className="detail-card__actions" />
      </div>
      {maxHeight === undefined ? children : (
        <div className="detail-card__scroll stack" role="group" aria-label={`${heading} content`} tabIndex={0}>{children}</div>
      )}
    </section>
    </DetailCardActionsContext.Provider>
  );
}
