/**
 * Module: modules/risk_management/ProjectRiskTypesPanel
 *
 * The project tier of the Risk type vocabulary — a thin wrapper over the shared
 * `ProjectTypeVocabularyPanel`, registered on `projectAdminSections` (Project
 * Admin). Gated server-side on the `risk_manager` role.
 */
import { ProjectTypeVocabularyPanel } from "../../components/TypeVocabularyPanels";
import { riskApi } from "./api";

const api = {
  list: riskApi.listTypes,
  createLocal: riskApi.createLocalType,
  override: riskApi.overrideType,
  delete: riskApi.deleteType,
  listHidden: riskApi.listHiddenTypes,
  restore: riskApi.restoreTypes,
};

export function ProjectRiskTypesPanel({ projectId }: { projectId: string }) {
  return (
    <ProjectTypeVocabularyPanel
      projectId={projectId}
      noun="Risk"
      api={api}
      description={
        <>
          This project's effective Risk type list — every active organisation type (with this project's own override, if
          any) plus any type added for this project only. Disabling or hiding a type here only affects this project.
        </>
      }
    />
  );
}
