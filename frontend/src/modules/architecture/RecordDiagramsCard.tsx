/**
 * Module: modules/architecture/RecordDiagramsCard
 *
 * The "Diagrams" card of an element or connection page: every block diagram that draws the record and, for an element, every
 * state machine diagram that describes it, in one list (code, name, type, how it appears, status), each a link to its editor.
 * The page places it directly under its details card, because it is the way to move to another view of the record.
 *
 * Design decisions: one read per record (`diagrams` on the element or connection API) answers both diagram types after the
 * server has applied visibility, so the card draws what it is given and holds no access rule of its own. A failed read leaves
 * the card out, so the page is as it was for a person the read does not serve.
 */
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { Badge } from "../../components/Badge";
import { DetailCard } from "../../components/DetailCard";
import { ScopedRecordCode } from "../../components/ScopedRecordCode";
import { projectConnectionApi, projectElementApi } from "./api";
import {
  ARCHITECTURE_STATUS_LABEL, ARCHITECTURE_STATUS_TONE, DIAGRAM_KIND_LABEL, RECORD_DIAGRAM_USAGE_LABEL, type RecordDiagram,
} from "./types";

/** The editor's address for a listed diagram. */
function editorPath(projectId: string, diagram: RecordDiagram): string {
  const folder = diagram.kind === "block" ? "diagrams" : "state-machine-diagrams";
  return `/projects/${projectId}/modules/architecture/${folder}/${diagram.id}`;
}

/** How the record appears on the diagram: "Placed", "Inside <ancestor>", "Drawn", "Rolled up" or "Describes this element". */
function Appearance({ diagram }: { diagram: RecordDiagram }) {
  if (diagram.usage !== "inside") return <>{RECORD_DIAGRAM_USAGE_LABEL[diagram.usage]}</>;
  return (
    <>
      Inside {diagram.via_element_code && <ScopedRecordCode record={{ unique_code: diagram.via_element_code }} />} {diagram.via_element_name}
    </>
  );
}

/**
 * @param projectId The record's project.
 * @param record The element or connection the card is for (its kind picks the read).
 * @param action A control on the heading's line (an element's New state machine diagram button).
 */
export function RecordDiagramsCard({
  projectId, record, action,
}: {
  projectId: string;
  record: { kind: "element" | "connection"; id: string };
  action?: ReactNode;
}) {
  const [diagrams, setDiagrams] = useState<RecordDiagram[] | null>(null);

  useEffect(() => {
    let live = true;
    const read = record.kind === "element" ? projectElementApi(projectId).diagrams(record.id) : projectConnectionApi(projectId).diagrams(record.id);
    read.then((list) => { if (live) setDiagrams(list); }).catch(() => { if (live) setDiagrams(null); });
    return () => { live = false; };
  }, [projectId, record.kind, record.id]);

  if (diagrams === null) return null;
  return (
    <DetailCard heading="Diagrams" action={action}>
      {diagrams.length === 0 ? <p className="text-muted" style={{ margin: 0 }}>Not on any diagram.</p> : (
        <ul style={{ margin: 0, paddingLeft: 0, listStyle: "none" }} className="stack">
          {diagrams.map((d) => (
            <li key={`${d.kind}-${d.id}`}>
              <Link to={editorPath(projectId, d)}>
                <ScopedRecordCode record={{ unique_code: d.unique_code }} /> {d.name}
              </Link>{" "}
              <span className="text-muted">{DIAGRAM_KIND_LABEL[d.kind]} · <Appearance diagram={d} /></span>{" "}
              <Badge tone={ARCHITECTURE_STATUS_TONE[d.status]}>{ARCHITECTURE_STATUS_LABEL[d.status]}</Badge>
            </li>
          ))}
        </ul>
      )}
    </DetailCard>
  );
}
