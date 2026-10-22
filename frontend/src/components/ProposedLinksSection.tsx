/**
 * Module: components/ProposedLinksSection
 *
 * The "Proposed links" card of a change request's page: each link the request proposes, drawn
 * like a link in the Links panel, with what became of it once the request is decided (merged,
 * left out by the approver, or not valid with the reason). A proposed link is not a link yet, so
 * it appears here and nowhere else; the requirement's Links panel shows it only after a merge.
 */
import type { ProposedLink } from "../api/types";
import { PROPOSED_LINK_OUTCOME_LABEL, PROPOSED_LINK_OUTCOME_TONE } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { ProposedLinkRow } from "./ProposedLinkRow";
import { Badge } from "./Badge";

export function ProposedLinksSection({ links, title }: { links: ProposedLink[]; title?: string }) {
  const strings = useStrings();
  return (
    <div className="stack" style={{ gap: "var(--space-3)" }} aria-label={title ?? strings.changeRequests.proposedLinks}>
      <strong>{title ?? strings.changeRequests.proposedLinks}</strong>
      <p className="text-muted" style={{ margin: 0 }}>{strings.changeRequests.proposedLinksHelp}</p>
      <ul className="artefact-links__list">
        {links.map((link) => (
          <ProposedLinkRow
            key={link.id}
            view={{
              phrase: link.phrase, label: link.other_label, typeLabel: link.other_type_label,
              projectName: link.other_project_name,
            }}
            trailing={
              <>
                <Badge tone={PROPOSED_LINK_OUTCOME_TONE[link.outcome]}>
                  {PROPOSED_LINK_OUTCOME_LABEL[link.outcome]}
                </Badge>
                {link.outcome_reason && <span className="text-muted">{link.outcome_reason}</span>}
              </>
            }
          />
        ))}
      </ul>
    </div>
  );
}
