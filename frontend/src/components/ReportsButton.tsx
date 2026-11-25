/**
 * Module: components/ReportsButton
 *
 * The "Reports" button at the top of the project and organisation overviews: opens the Reports dialog
 * (`ReportsDialog`) on the report chooser.
 *
 * Design decisions: the dialog is open while the `reports` search parameter is present (any value opens the chooser), so a
 * link can open it on a given `report` and `section` and Back closes it. Closing removes `reports`, `report` and
 * `section` and leaves every other parameter. Background reports are opened from a notification (`ReportRunDialog`).
 *
 * Dependencies: `ReportsDialog`.
 */
import { useSearchParams } from "react-router-dom";

import type { Project } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { ReportsDialog } from "./ReportsDialog";

/** The search parameter that holds the open dialog. */
export const REPORTS_PARAM = "reports";

/**
 * @param scope What the reports are for: a project or an organisation, by id.
 * @param organizationId The owning organisation.
 * @param project The project, when the scope is one (for the requirement report).
 */
export function ReportsButton({
  scope, organizationId, project,
}: {
  scope: { kind: "project" | "organization"; id: string };
  organizationId: string;
  project?: Project;
}) {
  const strings = useStrings();
  const [searchParams, setSearchParams] = useSearchParams();
  const open = searchParams.has(REPORTS_PARAM);

  function show(next: boolean) {
    const params = new URLSearchParams(searchParams);
    if (next) {
      params.set(REPORTS_PARAM, "choose");
    } else {
      for (const key of [REPORTS_PARAM, "report", "section"]) params.delete(key);
    }
    setSearchParams(params);
  }

  return (
    <>
      <button type="button" className="btn" onClick={() => show(true)}>{strings.reports.title}</button>
      {open && <ReportsDialog scope={scope} organizationId={organizationId} project={project} onClose={() => show(false)} />}
    </>
  );
}
