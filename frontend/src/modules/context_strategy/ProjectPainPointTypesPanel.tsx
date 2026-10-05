/**
 * Module: modules/context_strategy/ProjectPainPointTypesPanel
 *
 * The project-scoped tier of Pain Point's type vocabulary (Phase 0 Q3,
 * source overview §6.2) — a thin wrapper over the shared
 * `ProjectTypeVocabularyPanel` (`components/TypeVocabularyPanels.tsx`, which
 * documents the shared behaviour, including the client-side reorder and why
 * delete blocks instead of offering reassignment). Shows this project's
 * effective type list; a `pain_point_manager` can rename/reorder/disable an
 * org type's project-local override, add a project-local type, and delete an
 * override or local type.
 *
 * **Placement: `projectAdminSections` (Project Admin)**, matching
 * `DecisionTypesPanel.tsx` (Decided by: Agent).
 */
import { ProjectTypeVocabularyPanel } from "../../components/TypeVocabularyPanels";
import { projectPainPointApi } from "./api";

const api = {
  list: (projectId: string) => projectPainPointApi.listTypes(projectId),
  createLocal: (projectId: string, name: string, displayOrder?: number) =>
    projectPainPointApi.createLocalType(projectId, name, displayOrder),
  override: projectPainPointApi.overrideType,
  delete: projectPainPointApi.deleteType,
};

export function ProjectPainPointTypesPanel({ projectId }: { projectId: string }) {
  return (
    <ProjectTypeVocabularyPanel
      projectId={projectId}
      noun="Pain Point"
      api={api}
      description={
        <>
          This project's effective Pain Point type list — every active organisation type (with this project's own
          override, if any) plus any type added directly for this project only. Disabling a type here only affects
          this project; the organisation's own list (Org Management) is unaffected.
        </>
      }
    />
  );
}
