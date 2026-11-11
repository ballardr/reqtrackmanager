/**
 * Module: components/ActivityLinkEnds
 *
 * The Record column of a link event on the project History table: the two records the link joins, source above
 * target, each a link. An end the viewer cannot open is shown by its type only; another project's record opens in
 * its own project and is followed by that project's name. The Event column carries the verb and the relationship
 * (`describeLinkEventAction`); the aside and the overview widget, which have no Record column, use the one-line
 * form `describeActivityAction`.
 */
import { Link } from "react-router-dom";

import { describeLinkedRecord, linkEventVerb, type ChangeEntry, type LinkedRecord } from "../api/types";
import { getArtefactPath } from "../modules/artefactPaths";

/** One end as a link when the viewer can open it and the type has a page, else as text. */
function LinkedRecordItem({ end, projectId }: { end: LinkedRecord; projectId: string }) {
  const text = describeLinkedRecord(end, projectId);
  const to = end.entity_id === null ? null : getArtefactPath(end.entity_type, end.project_id ?? projectId, end.entity_id);
  return to ? <Link to={to}>{text}</Link> : <span>{text}</span>;
}

/**
 * @param entry A link event (`linked_records` has two ends); anything else renders nothing.
 * @param projectId The project whose history is shown.
 */
export function ActivityLinkEnds({ entry, projectId }: { entry: ChangeEntry; projectId: string }) {
  if (linkEventVerb(entry) === null) return null;
  const [source, target] = entry.linked_records ?? [];
  return (
    <span className="stack" style={{ gap: "0.15rem" }}>
      <LinkedRecordItem end={source} projectId={projectId} />
      <span><span aria-hidden="true">→ </span><LinkedRecordItem end={target} projectId={projectId} /></span>
    </span>
  );
}
