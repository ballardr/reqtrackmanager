/**
 * Module: modules/stakeholders/ProjectStakeholderTypesPanel
 *
 * The project tier of the Stakeholder type vocabulary — a thin wrapper over the
 * shared `ProjectTypeVocabularyPanel` (`components/TypeVocabularyPanels.tsx`),
 * registered on `projectAdminSections` (Project Admin). Gated server-side on
 * `stakeholder_owner`.
 */
import { ProjectTypeVocabularyPanel } from "../../components/TypeVocabularyPanels";
import { projectStakeholderApi } from "./api";

const api = {
  list: (projectId: string) => projectStakeholderApi.listTypes(projectId),
  createLocal: (projectId: string, name: string, displayOrder?: number) =>
    projectStakeholderApi.createLocalType(projectId, name, displayOrder),
  override: projectStakeholderApi.overrideType,
  delete: projectStakeholderApi.deleteType,
};

export function ProjectStakeholderTypesPanel({ projectId }: { projectId: string }) {
  return (
    <ProjectTypeVocabularyPanel
      projectId={projectId}
      noun="Stakeholder"
      api={api}
      description={
        <>
          This project's effective Stakeholder type list — every active organisation type (with this project's own
          override, if any) plus any type added for this project only. Disabling a type here only affects this
          project.
        </>
      }
    />
  );
}
