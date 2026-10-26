/**
 * Module: components/ReportExportButton
 *
 * The "report export trigger" pattern (`docs/ux-style-guide.md`) — a single
 * "Export" button that opens a `Popover` offering "Download PDF report"/
 * "Download Word report"/"Download CSV report," for a host page or panel whose report generation
 * needs no pre-generation configuration screen of its own (contrast the
 * dedicated `pages/ReportsPage.tsx`, which does). First built inline in
 * `OrgComplianceDashboard.tsx` (replacing two permanently-
 * visible adjacent buttons per style guide Principle 11) and duplicated
 * with `CsvImportWizard.tsx`'s own Export/Download-template Popover as
 * precedent; extracted here once a third and fourth caller
 * (`OrgComplianceStandardsPanel.tsx`, `OrgComplianceOutstandingPanel.tsx`,
 * `OutstandingPanel.tsx`) needed the identical PDF/CSV report shape, per
 * this codebase's own "extract a shared component once a pattern repeats,
 * and migrate the existing call sites onto it too" rule — `ProjectCompliancePage.tsx`'s
 * own pre-25b two-button layout (never fixed when the org dashboard's
 * identical layout was) is migrated onto this component in the same change,
 * rather than leaving a second, now-visibly-inconsistent copy of the old
 * anti-pattern behind.
 *
 * The host owns error handling: `onDownload` is expected to catch and
 * surface its own failure toast (each caller's message names what failed
 * to generate — "the organisation compliance report," "this project's
 * compliance report," etc.) — this component only tracks which kind (if
 * any) is mid-download, to disable the popover's own two buttons and swap
 * their label to "…", matching `CsvImportWizard.tsx`'s identical
 * `exporting` convention.
 */
import { Download } from "lucide-react";
import { useRef, useState } from "react";
import type { ReactNode } from "react";

import type { ReportFileKind } from "../api/reports";
import { Popover } from "./Popover";

const OPTION_LABEL: Record<ReportFileKind, string> = {
  pdf: "Download PDF report",
  docx: "Download Word report",
  csv: "Download CSV report",
  html: "Download HTML report",
  xlsx: "Download Excel report",
};

/**
 * `kinds` lists the formats on offer (default PDF and CSV, what the compliance
 * callers have); `label` renames the trigger when it sits beside a primary
 * download button ("More formats") rather than standing alone. `extras` adds
 * related downloads that are not a format of the report (a list's import
 * template) under the formats, and `note` is one muted line under them (columns
 * the personal-data policy left out).
 */
export function ReportExportButton<K extends ReportFileKind = "pdf" | "csv">({
  onDownload,
  kinds = ["pdf", "csv"] as K[],
  label = "Export",
  extras = [],
  note,
}: {
  onDownload: (kind: K) => Promise<void>;
  kinds?: readonly K[];
  label?: string;
  extras?: readonly { key: string; label: string; onSelect: () => void | Promise<void> }[];
  note?: ReactNode;
}) {
  const [downloading, setDownloading] = useState<K | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  async function handleDownload(kind: K) {
    setMenuOpen(false);
    setDownloading(kind);
    try {
      await onDownload(kind);
    } finally {
      setDownloading(null);
    }
  }

  return (
    <>
      <button ref={triggerRef} type="button" className="btn" onClick={() => setMenuOpen((v) => !v)}>
        <Download /> {downloading ? "Exporting…" : label}
      </button>
      {menuOpen && (
        <Popover anchorRef={triggerRef} title="Export" onClose={() => setMenuOpen(false)}>
          <div className="stack" style={{ gap: "var(--space-1)", minWidth: 180 }}>
            {kinds.map((kind) => (
              <button
                key={kind} type="button" className="btn" style={{ justifyContent: "flex-start" }} disabled={downloading !== null}
                onClick={() => handleDownload(kind)}
              >
                <Download /> {downloading === kind ? "…" : OPTION_LABEL[kind]}
              </button>
            ))}
            {extras.map((extra) => (
              <button
                key={extra.key} type="button" className="btn" style={{ justifyContent: "flex-start" }} disabled={downloading !== null}
                onClick={() => {
                  setMenuOpen(false);
                  void extra.onSelect();
                }}
              >
                <Download /> {extra.label}
              </button>
            ))}
            {note && <span className="text-muted" style={{ maxWidth: 260 }}>{note}</span>}
          </div>
        </Popover>
      )}
    </>
  );
}
