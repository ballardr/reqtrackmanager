/**
 * Module: components/ReportsMenuButton
 *
 * The "Reports" menu at the top of the project and organisation overviews: "Choose a report…" and "Background
 * reports…", each opening the Reports dialog (`ReportsDialog`) on that view.
 *
 * Design decisions: whether the dialog is open is the `reports` search parameter (`choose` or `runs`), so a link
 * (a report figure that points at another report, a bookmark) can open it on a given `report` and `section`, and
 * Back closes it. Closing removes `reports`, `report` and `section` and leaves every other parameter of the page
 * (the overview's project-scope filter) as it was.
 *
 * Dependencies: `MenuButton`, `ReportsDialog`.
 */
import { useSearchParams } from "react-router-dom";

import type { Project } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { MenuButton } from "./MenuButton";
import { ReportsDialog, type ReportsDialogView } from "./ReportsDialog";

/** The search parameter that holds the open view. */
export const REPORTS_PARAM = "reports";

/**
 * @param scope What the reports are for: a project or an organisation, by id.
 * @param organizationId The owning organisation.
 * @param project The project, when the scope is one (for the requirement report).
 */
export function ReportsMenuButton({
  scope, organizationId, project,
}: {
  scope: { kind: "project" | "organization"; id: string };
  organizationId: string;
  project?: Project;
}) {
  const strings = useStrings();
  const [searchParams, setSearchParams] = useSearchParams();
  const open = searchParams.get(REPORTS_PARAM);
  const view: ReportsDialogView | null = open === "choose" || open === "runs" ? open : null;

  function show(next: ReportsDialogView | null) {
    const params = new URLSearchParams(searchParams);
    if (next) {
      params.set(REPORTS_PARAM, next);
    } else {
      for (const key of [REPORTS_PARAM, "report", "section"]) params.delete(key);
    }
    setSearchParams(params);
  }

  return (
    <>
      <MenuButton
        label={strings.reports.title}
        menuLabel={strings.reports.menuLabel}
        items={[
          { key: "choose", label: strings.reports.chooseReport, onSelect: () => show("choose") },
          { key: "runs", label: strings.reports.backgroundReports, onSelect: () => show("runs") },
        ]}
      />
      {view && (
        <ReportsDialog scope={scope} organizationId={organizationId} project={project} view={view} onClose={() => show(null)} />
      )}
    </>
  );
}
