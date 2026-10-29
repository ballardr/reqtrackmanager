/**
 * Module: components/ReportDownloadDialog
 *
 * The "Download report" dialog of a record list, in two steps: (1) choose a report, from the same folder picker the
 * Reports dialog uses, then (2) configure it for the project (or organisation) and download it.
 *
 * Responsibilities:
 * - Load the project's or organisation's report catalogue and keep the entries whose `record_types` include the
 *   list's type, so a requirements list never offers an engagement report, and drop `view_only` reports (read on
 *   screen in the Reports dialog; their tables stay available as widgets). The catalogue already reflects module
 *   enablement, the caller's role and placements (folders, hidden reports), so nothing is re-checked here.
 * - Offer the report packs beside them (`useReportPackEntries`): a pack is listed when any report in it reads the
 *   list's type (the server derives `record_types` from its entries), filed by the same placements as in the Reports dialog.
 * - Step 2 names the report and the project it runs for, then shows its parameters, variables and format menu
 *   (`ReportRunner` with `showResult` off), or for a pack its variable form, counts and zip download
 *   (`ReportPackRunner`): the report is never previewed in the dialog.
 *
 * Design decisions: the catalogue is loaded when the dialog opens, not when the list page does, so a list that never
 * uses it costs no request. Reports carry their own filters, so the list's current filters are not passed on (the
 * list's own Export menu items already download the filtered rows).
 *
 * Dependencies: `useReportCatalogue`, `useReportPackEntries`, `useReportPlacements`, `useScopeName`, `ReportPickerPanel`,
 * `ReportRunner`, `StepIndicator`, `Modal`.
 */
import { useMemo, useState } from "react";

import { useStrings, useTerm } from "../context/TerminologyContext";
import { useOrgLabelCapitalized } from "../context/BrandingContext";
import { useReportCatalogue } from "../hooks/useReportCatalogue";
import { useReportPackEntries } from "../hooks/useReportPackEntries";
import { useReportPlacements } from "../hooks/useReportPlacements";
import { useScopeName } from "../hooks/useScopeName";
import { Modal } from "./Modal";
import { extraItem } from "../utils/extraReportItem";
import { ReportPickerPanel, type ReportPickerItem } from "./ReportPicker";
import { ReportRunner } from "./ReportRunner";
import { Spinner } from "./Spinner";
import { StepIndicator } from "./StepIndicator";

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
  const strings = useStrings();
  const text = strings.recordTables;
  const projectTerm = useTerm("project");
  const orgLabel = useOrgLabelCapitalized();
  const scope = useMemo(
    () => (ownedByOrganization ? { kind: "organization" as const, id: organizationId ?? "" } : { kind: "project" as const, id: projectId ?? "" }),
    [ownedByOrganization, organizationId, projectId],
  );
  const catalogue = useReportCatalogue(scope.kind, scope.id || undefined);
  const packScope = scope.id ? scope : undefined;
  const packs = useReportPackEntries(packScope, organizationId);
  const placements = useReportPlacements(packScope);
  const [chosen, setChosen] = useState<string | null>(null);
  const entries = useMemo(
    () => catalogue.entries.filter((e) => e.record_types.includes(recordType) && !e.view_only),
    [catalogue.entries, recordType],
  );
  const packEntries = useMemo(
    () => packs.entries.filter((e) => e.recordTypes?.includes(recordType)),
    [packs.entries, recordType],
  );
  const items = useMemo<ReportPickerItem[]>(
    () => [
      ...entries.map((e) => ({
        id: e.slug, title: e.title, description: e.description, folder: e.folder, kind: e.kind, favouriteKey: e.placement_key || e.slug,
      })),
      ...packEntries.map((e) => extraItem(e, placements)).filter((item): item is ReportPickerItem => item !== null),
    ],
    [entries, packEntries, placements],
  );
  const entry = entries.find((e) => e.slug === chosen);
  const pack = entry ? undefined : packEntries.find((e) => e.key === chosen);
  const chosenTitle = entry?.title ?? pack?.title;
  const scopeName = useScopeName(scope.kind, scope.id || undefined);
  const scopeLabel = scope.kind === "project" ? projectTerm.charAt(0).toUpperCase() + projectTerm.slice(1) : orgLabel;

  return (
    <Modal title={text.downloadReport} onClose={onClose} size="lg">
      {catalogue.loading || packs.loading ? (
        <Spinner label={text.downloadReportLoading} />
      ) : catalogue.error ? (
        <p role="alert">{catalogue.error}</p>
      ) : items.length === 0 ? (
        <p className="text-muted">{text.downloadReportNone(recordLabel)}</p>
      ) : (
        <div className="stack">
          <StepIndicator
            steps={[text.downloadReportStepChoose, text.downloadReportStepConfigure]}
            current={chosenTitle ? 1 : 0}
            label={text.downloadReportStepsLabel}
          />
          {chosenTitle ? (
            <>
              <div>
                <button type="button" className="btn" onClick={() => setChosen(null)}>{strings.common.back}</button>
              </div>
              <dl className="stack" style={{ margin: 0, gap: "var(--space-2)" }}>
                <div className="row" style={{ gap: "var(--space-3)" }}>
                  <dt className="text-muted">{text.downloadReportFor}</dt>
                  <dd style={{ margin: 0, fontWeight: 600 }}>{chosenTitle}</dd>
                </div>
                <div className="row" style={{ gap: "var(--space-3)" }}>
                  <dt className="text-muted">{scopeLabel}</dt>
                  <dd style={{ margin: 0, fontWeight: 600 }}>{scopeName ?? "…"}</dd>
                </div>
              </dl>
              {pack ? pack.render() : entry && <ReportRunner entry={entry} scope={scope} organizationId={organizationId} showResult={false} />}
            </>
          ) : (
            <>
              <p className="text-muted">{text.downloadReportIntro(recordLabel)}</p>
              <ReportPickerPanel pickerId="record-list-download" items={items} selectedId="" onSelect={setChosen} />
            </>
          )}
        </div>
      )}
    </Modal>
  );
}
