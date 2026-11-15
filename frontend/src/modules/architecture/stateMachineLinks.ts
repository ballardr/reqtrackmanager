/**
 * Module: modules/architecture/stateMachineLinks
 *
 * The addresses that join a block diagram and the state machine diagram of one of its elements, in both directions, so the
 * block's badge, the Selection card, the Outline and the state machine's return link all build them one way.
 *
 * Design decisions:
 * - The way there carries `?from=<block diagram id>` and the way back carries `?select=<element id>`. Neither is trusted:
 *   the state machine page ignores a `from` that does not name a block diagram of the project the person can read, and the
 *   block diagram page ignores a `select` that names no box it draws.
 */

/** The address of a state machine diagram's editor, opened from a block diagram (`fromDiagramId`) when given. */
export function stateMachinePath(projectId: string, machineId: string, fromDiagramId?: string): string {
  const path = `/projects/${projectId}/modules/architecture/state-machine-diagrams/${machineId}`;
  return fromDiagramId ? `${path}?from=${fromDiagramId}` : path;
}

/** The address of a block diagram's editor with an element's box selected and centred (`elementId`), when given. */
export function blockDiagramPath(projectId: string, diagramId: string, elementId?: string): string {
  const path = `/projects/${projectId}/modules/architecture/diagrams/${diagramId}`;
  return elementId ? `${path}?select=${elementId}` : path;
}
