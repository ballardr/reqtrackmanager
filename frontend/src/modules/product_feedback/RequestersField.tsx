/**
 * Module: modules/product_feedback/RequestersField
 *
 * The "Requested by" field: one search box that finds Stakeholders, Personas and Engagements to record as having
 * asked for a request. It is the shared `QuickLinkField` restricted to the "Requested by" link type (so the server
 * applies the usual link rules), shown by the create form, the edit form and the Demand card's add dialog. Nothing
 * is written here: the caller creates the links with `useCommitQuickLinks` once the request exists.
 */
import { QuickLinkField } from "../../components/QuickLinkField";
import type { ArtefactLinksApi, CollectedLink } from "../../api/artefactLinks";

/** The forward name of the seeded link type a request uses for "who asked" (`demand.REQUESTED_BY_FORWARD`). */
export const REQUESTED_BY_LINK = "Requested by";

/**
 * @param projectId The request's project.
 * @param value The requesters chosen so far.
 * @param onChange Called with the next list.
 * @param help Overrides the `(?)` text after the caption.
 * @param label The caption (default "Requested by").
 * @param titled Shows the caption as a bold section title (default: yes); false for a field inside a titled section.
 * @param api Injectable link calls (stories pass a fake).
 */
export function RequestersField({
  projectId, value, onChange, help = "Requesters are added when the request is saved.", label = "Requested by", titled = true, api,
}: {
  projectId: string; value: CollectedLink[]; onChange: (links: CollectedLink[]) => void; help?: string; label?: string;
  titled?: boolean; api?: ArtefactLinksApi;
}) {
  return (
    <QuickLinkField
      projectId={projectId} artefactType="enhancement_request" preferredType="stakeholder" onlyLinkNamed={REQUESTED_BY_LINK}
      label={label} placeholder="Search stakeholders, personas and engagements…" help={help} titled={titled}
      value={value} onChange={onChange} api={api}
    />
  );
}
