/**
 * Module: components/LinkedRecordSummary
 *
 * One linked record as the Links panel and the trace tree show it: the
 * relationship ("Implements"), the record (a link to its page), its status
 * through the owning module's label map, an archived flag, a project badge when
 * the record lives in another project, and a warning when the link's type no
 * longer permits the link.
 *
 * Two layouts. `inline` (trace tree) leads with the relationship as a pill.
 * `list` (Links panel) groups rows under their relationship, so it shows no
 * pill: the title is the link (named in full for assistive technology), the code
 * a muted suffix, and status, archived flag, carried-over note and project plain
 * muted text.
 *
 * Presentation only. It renders a fragment; the caller owns the row container.
 */
import { useRecordCode } from "../hooks/useRecordCode";
import { Link } from "react-router-dom";

import type { LinkGraphEdge, LinkGraphNode } from "../api/artefactLinks";
import { useStrings } from "../context/TerminologyContext";
import { getArtefactPath, getArtefactStatusLabel } from "../modules/artefactPaths";
import { splitArtefactCode } from "./artefactCode";
import { badgeClassName } from "./badgeClassName";
import { Badge } from "./Badge";

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
  layout = "inline",
}: {
  edge: LinkGraphEdge;
  node: LinkGraphNode;
  currentProjectId: string;
  /** Labels of hidden records the link was joined through (the trace's "Hide inactive records"). */
  via?: string[];
  /** `inline` (default): relationship pill first, badges after. `list`: grouped-list row, no pills. */
  layout?: "inline" | "list";
}) {
  const strings = useStrings();
  const recordCode = useRecordCode();
  const phrase = edge.phrase ?? strings.artefactLinks.untyped;
  const path = getArtefactPath(node.type, node.project_id ?? currentProjectId, node.id);
  const statusLabel = getArtefactStatusLabel(node.type, node.status);
  const elsewhere = node.project_id !== null && node.project_id !== currentProjectId;
  // A record the organisation owns is qualified by the organisation's code; one in another project by that project's.
  const ownerCode = node.organization_code ?? (elsewhere ? node.project_code : undefined);
  if (layout === "list") {
    const { code, title } = splitArtefactCode(node.label);
    return (
      <>
        <span className="artefact-links__target">
          {path ? <Link to={path} aria-label={node.label}>{title}</Link> : title}
          {code && <span className="artefact-links__code" title={node.label}>{recordCode.code(code, ownerCode)}</span>}
        </span>
        {statusLabel && <span className="artefact-links__meta">{statusLabel}</span>}
        {node.is_archived && <span className="artefact-links__meta">{strings.artefactLinks.archivedBadge}</span>}
        {edge.note && <span className="artefact-links__meta">{edge.note}</span>}
        {elsewhere && (
          <Link className="artefact-links__meta" to={`/projects/${node.project_id}`}>
            {strings.artefactLinks.otherProjectBadge(node.project_name ?? "")}
          </Link>
        )}
        {!edge.nesting_permitted && (
          <Badge tone="warning" title={strings.artefactLinks.notPermittedExplanation}>
            {strings.artefactLinks.notPermitted}
          </Badge>
        )}
      </>
    );
  }
  return (
    <>
      <Badge>{phrase}</Badge>
      <span className="artefact-links__target">{path ? <Link to={path}>{recordCode.label(node.label, ownerCode)}</Link> : recordCode.label(node.label, ownerCode)}</span>
      {statusLabel && <Badge tone="muted">{statusLabel}</Badge>}
      {node.is_archived && <Badge tone="muted">{strings.artefactLinks.archivedBadge}</Badge>}
      {elsewhere && (
        <Link className={badgeClassName("info")} to={`/projects/${node.project_id}`}>
          {strings.artefactLinks.otherProjectBadge(node.project_name ?? "")}
        </Link>
      )}
      {via.length > 0 && <span className="text-muted link-trace__via">{strings.artefactLinks.traceVia(via.join(", "))}</span>}
      {!edge.nesting_permitted && (
        <Badge tone="warning" title={strings.artefactLinks.notPermittedExplanation}>
          {strings.artefactLinks.notPermitted}
        </Badge>
      )}
    </>
  );
}
