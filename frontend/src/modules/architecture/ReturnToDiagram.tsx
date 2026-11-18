/**
 * Module: modules/architecture/ReturnToDiagram
 *
 * The way back from a state machine diagram to the block diagram it was opened from, drawn beside the header's back link.
 *
 * Responsibilities:
 * - With a `from` naming a block diagram of the project the person can read, a **Return** link to it that selects and centres
 *   the element's box (`?select=`).
 * - Without one (a reload from the list, a pasted link, an unreadable `from`), an **Open in diagram** menu of the block
 *   diagrams that draw the element (the Diagrams card's read), so the way back never depends on how the page was reached.
 * - Nothing when the element is drawn on no block diagram, or when the person cannot read the diagrams.
 *
 * Design decisions:
 * - `from` is not trusted: it is read through the project's own diagram API, so a diagram of another project or one the
 *   person cannot read answers 404 and is ignored.
 * - A diagram that only contains the element inside a drawn ancestor is offered too (the box is not drawn there, so nothing
 *   is selected, which the block diagram page allows).
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { MenuButton } from "../../components/MenuButton";
import { ReturnLink } from "../../components/ReturnLink";
import { useRecordCode } from "../../hooks/useRecordCode";
import { projectDiagramApi, projectElementApi } from "./api";
import { ARCHITECTURE_HELP } from "./help";
import { blockDiagramPath } from "./stateMachineLinks";
import type { RecordDiagram } from "./types";

/** A block diagram to go to: its id, code and name. */
interface Destination {
  id: string;
  unique_code: string;
  name: string;
}

/**
 * @param projectId The project of both diagrams.
 * @param elementId The element the state machine diagram describes.
 * @param from The `from` parameter of the address, or null.
 */
export function ReturnToDiagram({ projectId, elementId, from }: { projectId: string; elementId: string; from: string | null }) {
  const formatCode = useRecordCode();
  const navigate = useNavigate();
  const key = `${projectId}:${elementId}:${from ?? ""}`;
  /** What the reads found for `key`; a result for an earlier key is ignored (the inputs changed while it was loading). */
  const [found, setFound] = useState<{ key: string; origin: Destination | null; choices: Destination[] } | null>(null);

  useEffect(() => {
    let live = true;
    const settle = (origin: Destination | null, choices: Destination[]) => { if (live) setFound({ key, origin, choices }); };
    const fallback = () => projectElementApi(projectId).diagrams(elementId)
      .then((rows: RecordDiagram[]) => settle(null, rows.filter((r) => r.kind === "block")))
      .catch(() => settle(null, []));
    if (from) {
      projectDiagramApi(projectId).get(from)
        .then((d) => settle({ id: d.id, unique_code: d.unique_code, name: d.name }, []))
        .catch(() => void fallback());
    } else {
      void fallback();
    }
    return () => { live = false; };
  }, [key, projectId, elementId, from]);

  const current = found?.key === key ? found : null;
  const origin = current?.origin ?? null;
  const choices = current?.choices ?? [];

  if (origin) {
    return <ReturnLink to={blockDiagramPath(projectId, origin.id, elementId)} label={`${formatCode.code(origin.unique_code)} ${origin.name}`} />;
  }
  if (choices.length === 0) return null;
  return (
    <MenuButton
      label="Open in diagram" size="sm" menuLabel="Block diagrams that draw this element" help={ARCHITECTURE_HELP.openInDiagram}
      items={choices.map((c) => ({
        key: c.id, label: `${formatCode.code(c.unique_code)} ${c.name}`, onSelect: () => navigate(blockDiagramPath(projectId, c.id, elementId)),
      }))}
    />
  );
}
