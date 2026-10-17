/**
 * Module: components/ProposedLinkRow
 *
 * One link proposed on a change request, drawn the way the Links panel draws a link
 * (relationship badge, the record, its type, the {project} it lives in) so a proposed link
 * reads like a real one. Shared by the form that collects them (`ProposedLinksEditor`), the
 * request page (`ProposedLinksSection`) and the approval dialog (`ApproveChangeRequestDialog`),
 * which differ only in the controls around the row and what is shown after it.
 *
 * A record the viewer cannot see arrives without a label and is drawn as a neutral
 * placeholder; nothing about it is revealed.
 */
import type { ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";
import { Badge } from "./Badge";
import { ItemRow } from "./ItemRow";

/** What a row needs to draw, independent of whether it was collected, stored or previewed. */
export interface ProposedLinkView {
  /** The relationship as the requirement reads it; null once the link type is gone. */
  phrase: string | null;
  /** The record's title, or null when the viewer cannot see it. */
  label: string | null;
  typeLabel: string;
  /** The {project} the record lives in when it is not the request's own. */
  projectName?: string | null;
}

export function ProposedLinkRow({
  view,
  leading,
  trailing,
  actions,
  muted = false,
}: {
  view: ProposedLinkView;
  /** A control before the row (the approval dialog's checkbox). */
  leading?: ReactNode;
  /** Badges or a reason after the row; wraps with the text. */
  trailing?: ReactNode;
  /** Controls (a remove button) that stay beside the row however long its text is. */
  actions?: ReactNode;
  /** Drawn greyed out (a link that cannot be merged). */
  muted?: boolean;
}) {
  const strings = useStrings();
  return (
    <ItemRow as="li" className="artefact-links__row" style={muted ? { opacity: 0.75 } : undefined} actions={actions}>
      <div className="artefact-links__summary" data-wrap-ok>
        {leading}
        <Badge>{view.phrase ?? "—"}</Badge>
        <span className="artefact-links__target">{view.label ?? strings.changeRequests.hiddenRecord}</span>
        <Badge tone="muted">{view.typeLabel}</Badge>
        {view.projectName && <Badge tone="info">{strings.artefactLinks.otherProjectBadge(view.projectName)}</Badge>}
        {trailing}
      </div>
    </ItemRow>
  );
}
