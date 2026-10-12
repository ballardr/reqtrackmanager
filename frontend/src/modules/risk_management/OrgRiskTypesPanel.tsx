/**
 * Module: modules/risk_management/OrgRiskTypesPanel
 *
 * The organisation tier of the Risk type vocabulary (Phase 0 resolution 2) — a
 * thin wrapper over the shared `OrgTypeVocabularyPanel`. Registered on
 * `orgAdminSections` (Org Management). Gated server-side on `risk_type_admin`.
 */
import { OrgTypeVocabularyPanel } from "../../components/TypeVocabularyPanels";
import { orgRiskTypeApi } from "./api";

export function OrgRiskTypesPanel({ orgId }: { orgId: string }) {
  return (
    <OrgTypeVocabularyPanel
      orgId={orgId}
      noun="Risk"
      api={orgRiskTypeApi}
      inUseMessage="This type is still used by at least one project or risk. Disable it instead of deleting it."
      description={
        <>
          The shared Risk type vocabulary every project in this organisation sees by default (Safety, Technical,
          Security, Schedule and the rest are seeded for a new organisation). A project may locally rename, disable, or
          add its own types without affecting this list or any other project.
        </>
      }
    />
  );
}
