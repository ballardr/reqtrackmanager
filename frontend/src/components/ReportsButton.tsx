/**
 * Module: components/ReportsButton
 *
 * The "Reports" button at the top of the project and organisation overviews: one click opens the Reports dialog
 * (`ReportsDialog`) on the report chooser.
 *
 * Design decisions: whether the dialog is open is the `reports` search parameter, so a link (a report figure that
 * points at another report, a bookmark) can open it on a given `report` and `section`, and Back closes it. Any value
 * opens the chooser, so an old `?reports=runs` link lands there. Closing removes `reports`, `report` and `section`
 * and leaves every other parameter of the page (the overview's project-scope filter) as it was. Background reports
 * have no view of their own: a notification opens the report (`ReportRunDialog`) and the top bar shows what is
 * still being prepared (`ReportRunsIndicator`).
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
