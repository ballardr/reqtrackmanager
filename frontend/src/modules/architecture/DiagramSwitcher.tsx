/**
 * Module: architecture/DiagramSwitcher
 *
 * The chevron beside a diagram's title that switches to another diagram of the same kind in the project, the same
 * quick-switch the project and organisation pages have (`EntitySwitcher`).
 *
 * Responsibilities:
 * - Load the project's live (not archived) block diagrams or state machine diagrams and offer each as a link to its editor,
 *   labelled by its code (through the record-code rule) and name.
 *
 * Design decisions:
 * - One switcher per kind: a block diagram and a state machine diagram are different record types with different pages, so a
 *   block diagram's list never offers a state machine diagram.
 * - The options are reloaded when the current diagram changes, so a renamed diagram does not keep its old label.
 *
 * Dependencies: `EntitySwitcher`, the architecture API client, `useRecordCode`.
 */
import { useCallback } from "react";

import { EntitySwitcher, type EntitySwitcherOption } from "../../components/EntitySwitcher";
import { useRecordCode } from "../../hooks/useRecordCode";
import { projectDiagramApi, projectStateMachineApi } from "./api";

/** The kinds of diagram the switcher lists, with the accessible name of the trigger and the path segment of their editor. */
const KINDS = {
  block: { label: "Switch diagram", segment: "diagrams" },
  stateMachine: { label: "Switch state machine diagram", segment: "state-machine-diagrams" },
} as const;

/**
 * @param kind Which diagrams are offered: block diagrams or state machine diagrams.
 * @param projectId The project whose diagrams are listed.
 * @param currentId The diagram the page shows; it is left out of the list.
 * @returns The chevron and its list; nothing while the project has no other diagram of the kind.
 */
export function DiagramSwitcher({ kind, projectId, currentId }: { kind: keyof typeof KINDS; projectId: string; currentId: string }) {
  const { code } = useRecordCode();
  const { label, segment } = KINDS[kind];
  const loadOptions = useCallback(async (): Promise<EntitySwitcherOption[]> => {
    const diagrams = kind === "block"
      ? await projectDiagramApi(projectId).list({ include_archived: false })
      : await projectStateMachineApi(projectId).list({ include_archived: false });
    return diagrams.map((d) => ({
      id: d.id, label: `${code(d.unique_code)} ${d.name}`, href: `/projects/${projectId}/modules/architecture/${segment}/${d.id}`,
    }));
  }, [kind, projectId, segment, code]);
  return <EntitySwitcher label={label} currentId={currentId} loadOptions={loadOptions} reloadKey={`${kind}:${projectId}`} />;
}
