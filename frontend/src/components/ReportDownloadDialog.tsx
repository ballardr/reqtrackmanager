/**
 * Module: components/ReportDownloadDialog
 *
 * The "Download report" dialog of a record list: the reports that use the list's record type, found in the same
 * folder picker the Reports page uses, then the chosen report run and downloadable in place (`ReportRunner`).
 *
 * Responsibilities:
 * - Load the project's or organisation's report catalogue and keep the entries whose `record_types` include the
 *   list's type, so a requirements list never offers an engagement report. The catalogue already reflects module
 *   enablement, the caller's role and placements (folders, hidden reports), so nothing is re-checked here.
 * - Offer them through `ReportPickerPanel` (folders, search, favourites); a pick shows the report with a way back
 *   to the choice.
 *
 * Design decisions: the catalogue is loaded when the dialog opens, not when the list page does, so a list that never
 * uses it costs no request. Reports carry their own filters, so the list's current filters are not passed on (the
 * list's own Export menu items already download the filtered rows).
 *
 * Dependencies: `useReportCatalogue`, `ReportPickerPanel`, `ReportRunner`, `Modal`.
 */
import { useMemo, useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { useReportCatalogue } from "../hooks/useReportCatalogue";
import { Modal } from "./Modal";
import { ReportPickerPanel, type ReportPickerItem } from "./ReportPicker";
import { ReportRunner } from "./ReportRunner";
import { Spinner } from "./Spinner";

/**
 * @param projectId The project whose list this is (give this or `organizationId`).
 * @param organizationId The organisation whose own list this is, or the project's organisation (branding templates).
 * @param ownedByOrganization True when the list is an organisation's own, so the organisation catalogue is used.
 * @param recordType The registered record type of the list.
 * @param recordLabel The type's plural label ("Requirements"), for the title and messages.
 * @param onClose Closes the dialog.
 */
export function ReportDownloadDialog({
  projectId, organizationId, ownedByOrganization, recordType, recordLabel, onClose,
}: {
  projectId?: string;
  organizationId?: string;
  ownedByOrganization: boolean;
  recordType: string;
  recordLabel: string;
  onClose: () => void;
}) {
  const text = useStrings().recordTables;
  const scope = useMemo(
    () => (ownedByOrganization ? { kind: "organization" as const, id: organizationId ?? "" } : { kind: "project" as const, id: projectId ?? "" }),
    [ownedByOrganization, organizationId, projectId],
  );
  const catalogue = useReportCatalogue(scope.kind, scope.id || undefined);
  const [chosen, setChosen] = useState<string | null>(null);
  const entries = useMemo(() => catalogue.entries.filter((e) => e.record_types.includes(recordType)), [catalogue.entries, recordType]);
  const items = useMemo<ReportPickerItem[]>(
    () => entries.map((e) => ({
      id: e.slug, title: e.title, description: e.description, folder: e.folder, kind: e.kind, favouriteKey: e.placement_key || e.slug,
    })),
    [entries],
  );
  const entry = entries.find((e) => e.slug === chosen);

  return (
    <Modal title={text.downloadReport} onClose={onClose} size="lg">
      {catalogue.loading ? (
        <Spinner label={text.downloadReportLoading} />
      ) : catalogue.error ? (
        <p role="alert">{catalogue.error}</p>
      ) : entries.length === 0 ? (
        <p className="text-muted">{text.downloadReportNone(recordLabel)}</p>
      ) : entry ? (
        <div className="stack">
          <div>
            <button type="button" className="btn" onClick={() => setChosen(null)}>{text.downloadReportBack}</button>
          </div>
          <ReportRunner entry={entry} scope={scope} organizationId={organizationId} />
        </div>
      ) : (
        <div className="stack">
          <p className="text-muted">{text.downloadReportIntro(recordLabel)}</p>
          <ReportPickerPanel pickerId="record-list-download" items={items} selectedId="" onSelect={setChosen} />
        </div>
      )}
    </Modal>
  );
}
