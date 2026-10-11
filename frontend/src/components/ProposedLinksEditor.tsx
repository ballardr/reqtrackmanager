/**
 * Module: components/ProposedLinksEditor
 *
 * The "Proposed links" section of the form that drafts a new or modify-requirement change
 * request: the links collected so far and the "Add a link" dialog (`AddArtefactLinkModal` in
 * its collect mode), so proposing a link uses the same finder, relationships and project choice
 * as adding one on the Links panel. Nothing is created here; the parent sends the collected
 * links with the request and the server validates each (and again on approval).
 *
 * Which requirement the links are for decides what the finder reads: an existing requirement's
 * own id, or `DRAFT_ARTEFACT_ID` for one the request would create. A user who may not link
 * requirements gets nothing at all (the link graph says so for an existing requirement, the
 * finder answers 403 for a draft one), so the section never offers what the server will refuse.
 */
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { artefactLinksApi, DRAFT_ARTEFACT_ID, type ArtefactLinksApi, type CollectedLink } from "../api/artefactLinks";
import { useStrings } from "../context/TerminologyContext";
import { AddArtefactLinkModal } from "./AddArtefactLinkModal";
import { ProposedLinkRow } from "./ProposedLinkRow";

const REQUIREMENT = "requirement";

export function ProposedLinksEditor({
  projectId,
  artefactId,
  links,
  onChange,
  api = artefactLinksApi,
}: {
  projectId: string;
  /** The requirement the links are for (`DRAFT_ARTEFACT_ID` when the request creates it). */
  artefactId: string;
  links: CollectedLink[];
  onChange: (links: CollectedLink[]) => void;
  api?: ArtefactLinksApi;
}) {
  const strings = useStrings();
  const [adding, setAdding] = useState(false);
  // Whether the caller may set requirement links here, tagged with what it was asked about so an
  // answer for an earlier requirement is never read for a later one; unknown until the answer arrives.
  const probeKey = `${projectId}:${artefactId}`;
  const [probed, setProbed] = useState<{ key: string; can: boolean } | null>(null);

  useEffect(() => {
    let active = true;
    const probe = artefactId === DRAFT_ARTEFACT_ID
      ? api.options(projectId, REQUIREMENT, artefactId).then(() => true)
      : api.graph(projectId, REQUIREMENT, artefactId).then((graph) => graph.can_propose);
    probe
      .then((can) => {
        if (active) setProbed({ key: probeKey, can });
      })
      .catch(() => {
        if (active) setProbed({ key: probeKey, can: false });
      });
    return () => {
      active = false;
    };
  }, [api, projectId, artefactId, probeKey]);

  const allowed = probed?.key === probeKey && probed.can;

  if (!allowed) return null;

  return (
    <div className="stack" style={{ gap: "0.5rem" }} role="group" aria-label={strings.changeRequests.proposedLinks}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>{strings.changeRequests.proposedLinks}</strong>
        <button type="button" className="btn" onClick={() => setAdding(true)}>
          <Plus size={14} /> {strings.changeRequests.addProposedLink}
        </button>
      </div>
      <p className="text-muted" style={{ margin: 0 }}>{strings.changeRequests.proposedLinksEditorHelp}</p>
      {links.length === 0 ? (
        <p className="text-muted" style={{ margin: 0 }}>{strings.changeRequests.noProposedLinks}</p>
      ) : (
        <ul className="artefact-links__list">
          {links.map((link, index) => (
            <ProposedLinkRow
              key={`${link.link_type_id}:${link.direction}:${link.other_type}:${link.other_id}`}
              view={{
                phrase: link.phrase, label: link.otherLabel, typeLabel: link.otherTypeLabel,
                projectName: link.otherProjectLabel,
              }}
              trailing={
                <button
                  type="button"
                  className="btn btn-danger artefact-links__remove"
                  title={strings.common.remove}
                  aria-label={strings.changeRequests.removeProposedLinkLabel(link.phrase, link.otherLabel)}
                  onClick={() => onChange(links.filter((_, i) => i !== index))}
                >
                  <Trash2 size={14} />
                </button>
              }
            />
          ))}
        </ul>
      )}
      {adding && (
        <AddArtefactLinkModal
          projectId={projectId}
          artefactType={REQUIREMENT}
          artefactId={artefactId}
          api={api}
          collect={{
            onCollect: (link) => {
              const key = (l: CollectedLink) => `${l.link_type_id}:${l.direction}:${l.other_type}:${l.other_id}`;
              if (!links.some((existing) => key(existing) === key(link))) onChange([...links, link]);
            },
          }}
          onAdded={() => setAdding(false)}
          onClose={() => setAdding(false)}
        />
      )}
    </div>
  );
}
