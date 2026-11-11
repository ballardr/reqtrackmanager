/**
 * Module: components/ReportFormatDownload
 *
 * The download step of a report: the formats the report offers as a radio list, and one Download button.
 *
 * Responsibilities:
 * - List each format by its one name (`REPORT_FORMAT`) with its full name as a tooltip; a report offering a single
 *   format shows that format and the button, not a one-item list.
 * - Preselect the format the person last downloaded (`REPORT_FORMAT_PREFERENCE`, per person across reports), PDF
 *   when there is no history, and the report's first format when it does not offer that one. Choosing an option
 *   remembers nothing; the format is recorded only once a download has gone through.
 * - Disable the button and say why in the same place when the report cannot be produced yet (`blockedReason`),
 *   so the reason is read with the button.
 *
 * Design decisions: it neither runs nor names the report; `onDownload` is the host's job and resolves `true` when a
 * file was delivered or queued and `false` when it failed (the host has already shown the error), which is what
 * decides whether the choice is remembered. A radio, not a checkbox list: one download is one run and one file.
 */
import { Download } from "lucide-react";
import { useId, useState } from "react";

import { REPORT_FORMAT } from "../api/reportFormats";
import type { ReportFileKind } from "../api/reports";
import { useStrings } from "../context/TerminologyContext";
import { useUiPreference } from "../hooks/useUiPreference";
import { Tooltip } from "./Tooltip";
import { defaultReportFormat, REPORT_FORMAT_PREFERENCE } from "../utils/reportFormatChoice";

/**
 * @param kinds The formats on offer (at least one).
 * @param onDownload Produces the file in the chosen format; resolves `true` when it was delivered or queued.
 * @param blockedReason Why the report cannot be downloaded yet; the button is disabled while it is set.
 */
export function ReportFormatDownload<K extends ReportFileKind>({
  kinds, onDownload, blockedReason,
}: {
  kinds: readonly K[];
  onDownload: (kind: K) => Promise<boolean>;
  blockedReason?: string;
}) {
  const strings = useStrings();
  const text = strings.reportRuns;
  const groupName = useId();
  const reasonId = useId();
  const [remembered, remember] = useUiPreference<string>(REPORT_FORMAT_PREFERENCE, "");
  const [picked, setPicked] = useState<K | null>(null);
  const [downloading, setDownloading] = useState(false);
  if (kinds.length === 0) return null;
  const selected = picked !== null && kinds.includes(picked) ? picked : defaultReportFormat(kinds, remembered);

  async function download() {
    setDownloading(true);
    try {
      if (await onDownload(selected)) remember(selected);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      {kinds.length > 1 ? (
        <fieldset className="stack" style={{ gap: "var(--space-1)", border: 0, margin: 0, padding: 0, minWidth: 0 }}>
          <legend style={{ fontWeight: 600, padding: 0, marginBottom: "var(--space-1)" }}>{text.formatLegend}</legend>
          {kinds.map((kind) => (
            <Tooltip key={kind} label={REPORT_FORMAT[kind].title}>
              <label className="checkbox-label">
                <input
                  type="radio" name={groupName} value={kind} checked={kind === selected}
                  disabled={downloading} onChange={() => setPicked(kind)}
                />
                <span>{REPORT_FORMAT[kind].label}</span>
              </label>
            </Tooltip>
          ))}
        </fieldset>
      ) : (
        <Tooltip label={REPORT_FORMAT[selected].title}>
          <p className="text-muted" style={{ margin: 0 }}>{text.formatOnly(REPORT_FORMAT[selected].label)}</p>
        </Tooltip>
      )}
      <div className="row">
        <button
          type="button" className="btn btn-primary" disabled={downloading || !!blockedReason}
          aria-describedby={blockedReason ? reasonId : undefined} onClick={() => void download()}
        >
          <Download /> {downloading ? text.downloading : text.download}
        </button>
        {blockedReason && (
          <span id={reasonId} role="status" className="text-muted">{blockedReason}</span>
        )}
      </div>
    </div>
  );
}
