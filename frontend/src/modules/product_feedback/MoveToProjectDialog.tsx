/**
 * Module: modules/product_feedback/MoveToProjectDialog
 *
 * Triages an inbox request into one of the organisation's projects. The request keeps its history and comments, takes
 * the project's next code, and its tags and files become the project's. The move is one-way and refused while the
 * request has links, which the dialog says up front. The server decides whether the person may submit in the chosen
 * project; a refusal is shown in the dialog.
 */
import { useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { LabeledSelect } from "../../components/LabeledSelect";

/**
 * @param code The request's current code, for the title.
 * @param projects The organisation's projects to choose from.
 * @param error A refusal from the server, shown in the dialog.
 * @param onMove Called with the chosen project's id; the caller closes the dialog on success.
 * @param onCancel Dismisses the dialog.
 */
export function MoveToProjectDialog({
  code, projects, error, onMove, onCancel,
}: {
  code: string;
  projects: { id: string; name: string }[];
  error?: string | null;
  onMove: (projectId: string) => void | Promise<void>;
  onCancel: () => void;
}) {
  const [projectId, setProjectId] = useState("");
  return (
    <ConfirmDialog
      title={`Move ${code} into a project?`}
      message={
        <span className="stack" style={{ gap: "var(--space-3)" }}>
          <span>
            The request keeps its history and comments and is renumbered in the project. This cannot be undone, and a
            request that has links cannot be moved.
          </span>
          <LabeledSelect
            helpNotNeeded required label="Project" value={projectId} onChange={setProjectId}
            options={projects.map((p) => ({ value: p.id, label: p.name }))} placeholder="Choose a project…"
          />
          {error && <span role="alert" className="text-danger">{error}</span>}
        </span>
      }
      confirmLabel="Move"
      confirmDisabled={projectId === ""}
      onConfirm={() => void onMove(projectId)}
      onCancel={onCancel}
    />
  );
}
