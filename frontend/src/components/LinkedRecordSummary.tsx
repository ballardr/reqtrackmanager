/**
 * Module: components/LinkedRecordSummary
 *
 * One linked record as the Links panel and the trace tree both show it: the
 * relationship ("Implements"), the record (a link to its page), its status
 * through the owning module's label map, an archived flag, a badge naming
 * another project when the record lives in one, and a warning when the link's
 * type no longer permits the link.
 *
 * Responsibilities: presentation only. It renders a fragment, so the caller
 * owns the row container (and any controls beside it, such as Remove).
 */
import { Link } from "react-router-dom";

import type { LinkGraphEdge, LinkGraphNode } from "../api/artefactLinks";
import { useStrings } from "../context/TerminologyContext";
import { getArtefactPath, getArtefactStatusLabel } from "../modules/artefactPaths";

/**
 * Renders the badges and link for one edge and the record at its far end.
 *
 * @param edge The link being shown (its phrase and permitted flag are used).
 * @param node The record at the far end.
 * @param currentProjectId The project the page is in, so records elsewhere get a project badge.
 * @param via Hidden records the link was joined through, shown after the record ("via DEC-001").
 */
export function LinkedRecordSummary({
  edge,
  node,
  currentProjectId,
  via = [],
}: {
  edge: LinkGraphEdge;
  node: LinkGraphNode;
  currentProjectId: string;
  /** Labels of hidden records the link was joined through (the trace's "Hide inactive records"). */
  via?: string[];
}) {
  const strings = useStrings();
  const phrase = edge.phrase ?? strings.artefactLinks.untyped;
  const path = getArtefactPath(node.type, node.project_id ?? currentProjectId, node.id);
  const statusLabel = getArtefactStatusLabel(node.type, node.status);
  const elsewhere = node.project_id !== null && node.project_id !== currentProjectId;
  return (
    <>
      <span className="badge">{phrase}</span>
      <span className="artefact-links__target">{path ? <Link to={path}>{node.label}</Link> : node.label}</span>
      {statusLabel && <span className="badge badge--muted">{statusLabel}</span>}
      {node.is_archived && <span className="badge badge--muted">{strings.artefactLinks.archivedBadge}</span>}
      {elsewhere && (
        <Link className="badge badge--info" to={`/projects/${node.project_id}`}>
          {strings.artefactLinks.otherProjectBadge(node.project_name ?? "")}
        </Link>
      )}
      {via.length > 0 && <span className="text-muted link-trace__via">{strings.artefactLinks.traceVia(via.join(", "))}</span>}
      {!edge.nesting_permitted && (
        <span className="badge badge--warning" title={strings.artefactLinks.notPermittedExplanation}>
          {strings.artefactLinks.notPermitted}
        </span>
      )}
    </>
  );
}
