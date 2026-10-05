/**
 * Module: modules/stakeholders/HeldNeedsPanel
 *
 * The read-only "Needs" list on a Stakeholder's or Persona's detail page: the
 * Stakeholder Needs of the current project that the record has ("has need"
 * links, owned from the Need's side, so nothing is edited here). It is the
 * shared `RepresentationPanel` without `edit`, so it hides itself when the
 * Stakeholder Needs sub-component is off, and shows nothing on the org-level
 * detail route, where no single project's needs apply.
 */
import { RepresentationPanel } from "./RepresentationPanel";
import type { HeldNeed } from "./types";
import { NEED_STATUS_LABEL } from "./types";

export function HeldNeedsPanel({
  projectId,
  load,
}: {
  /** The project whose needs are listed; `undefined` on the org route renders nothing. */
  projectId: string | undefined;
  load: () => Promise<HeldNeed[]>;
}) {
  if (!projectId) return null;
  return (
    <RepresentationPanel
      heading="Needs"
      emptyText="No Stakeholder Needs recorded for this yet."
      load={async () =>
        (await load()).map((n) => ({ link_id: n.link_id, id: n.id, name: `${n.name} (${NEED_STATUS_LABEL[n.status]})`, scope: "project" as const }))
      }
      linkFor={(need) => `/projects/${projectId}/modules/stakeholders/needs/${need.id}`}
    />
  );
}
