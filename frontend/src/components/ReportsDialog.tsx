/**
 * Module: components/ReportsDialog
 *
 * The one place reports are chosen and downloaded for a project or an organisation: a dialog opened from the
 * "Reports" menu on the project and organisation overviews (`ReportsMenuButton`). It has two views: the report
 * picker with the chosen report below it (`ReportCatalogue`), and the person's background reports.
 *
 * Responsibilities:
 * - Load the scope's report catalogue and report packs when the dialog opens, so an overview that never opens it
 *   costs no extra request, and offer them (with the requirement report for a project) in the one picker.
 * - Show the person's background reports (`ReportRunsPanel`) in their own view.
 *
 * Design decisions: nothing here names a module or a report; the catalogue says what exists. The chosen report is
 * the `report` search parameter and a figure's target section the `section` parameter (read by `ReportCatalogue`),
 * so a link can open the dialog on one report.
 *
 * Dependencies: `ReportCatalogue`, `ReportRunsPanel`, `useReportCatalogue`, `useReportPackEntries`, `Modal`.
 */
import { useMemo } from "react";

import { PLACEMENT_KEY_REQUIREMENTS } from "../api/reportPlacements";
import type { Project } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { useReportCatalogue } from "../hooks/useReportCatalogue";
import { useReportPackEntries } from "../hooks/useReportPackEntries";
import { Modal } from "./Modal";
import { ReportCatalogue, type ExtraReportEntry } from "./ReportCatalogue";
import { ReportRunsPanel } from "./ReportRunsPanel";
import { RequirementReportPanel } from "./RequirementReportPanel";
import { Spinner } from "./Spinner";

/** Which view the dialog opens on. */
export type ReportsDialogView = "choose" | "runs";

/**
 * @param scope What the reports are for: a project or an organisation, by id.
 * @param organizationId The owning organisation (branding templates and background reports).
 * @param project The project, for the requirement report; omit for an organisation.
 * @param view `choose` for the report picker, `runs` for the person's background reports.
 * @param onClose Closes the dialog.
 */
export function ReportsDialog({
  scope, organizationId, project, view, onClose,
}: {
  scope: { kind: "project" | "organization"; id: string };
  organizationId: string;
  project?: Project;
  view: ReportsDialogView;
  onClose: () => void;
}) {
  const strings = useStrings();
  const catalogue = useReportCatalogue(scope.kind, scope.id);
  const packScope = useMemo(() => ({ kind: scope.kind, id: scope.id }), [scope.kind, scope.id]);
  const packs = useReportPackEntries(packScope, organizationId);
  const extraEntries = useMemo<ExtraReportEntry[]>(
    () => [
      ...(project
        ? [{
            key: "requirements",
            title: "Requirements report",
            placementKey: PLACEMENT_KEY_REQUIREMENTS,
            description: "The project's requirements as a document, with filters, resource sections and a chapter layout.",
            render: () => <RequirementReportPanel project={project} />,
          }]
        : []),
      ...packs.entries,
    ],
    [project, packs.entries],
  );

  return (
    <Modal title={view === "runs" ? strings.reportRuns.title : strings.reports.title} onClose={onClose} size="lg">
      {view === "runs" ? (
        <ReportRunsPanel organizationId={organizationId} emptyMessage={strings.reportRuns.empty} />
      ) : catalogue.loading || packs.loading ? (
        <Spinner />
      ) : (
        <ReportCatalogue entries={catalogue.entries} scope={scope} organizationId={organizationId} extraEntries={extraEntries} />
      )}
    </Modal>
  );
}
