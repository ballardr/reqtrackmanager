/**
 * Module: components/ReportExportButton
 *
 * The "report export trigger" pattern (`docs/ux-style-guide.md`) — a single
 * "Export" button that opens a `Popover` offering "Download PDF report"/
 * "Download CSV report," for a host page or panel whose report generation
 * needs no pre-generation configuration screen of its own (contrast the
 * dedicated `pages/ReportsPage.tsx`, which does). First built inline in
 * `OrgComplianceDashboard.tsx` (Phase 25b, replacing two permanently-
 * visible adjacent buttons per style guide Principle 11) and duplicated
 * with `CsvImportWizard.tsx`'s own Export/Download-template Popover as
 * precedent; extracted here (Phase 43) once a third and fourth caller
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

import { Popover } from "./Popover";

export function ReportExportButton({ onDownload }: { onDownload: (kind: "pdf" | "csv") => Promise<void> }) {
  const [downloading, setDownloading] = useState<"pdf" | "csv" | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  async function handleDownload(kind: "pdf" | "csv") {
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
        <Download size={16} /> {downloading ? "Exporting…" : "Export"}
      </button>
      {menuOpen && (
        <Popover anchorRef={triggerRef} title="Export" onClose={() => setMenuOpen(false)}>
          <div className="stack" style={{ gap: "0.25rem", minWidth: 180 }}>
            <button
              type="button" className="btn" style={{ justifyContent: "flex-start" }} disabled={downloading !== null}
              onClick={() => handleDownload("pdf")}
            >
              <Download size={14} /> {downloading === "pdf" ? "…" : "Download PDF report"}
            </button>
            <button
              type="button" className="btn" style={{ justifyContent: "flex-start" }} disabled={downloading !== null}
              onClick={() => handleDownload("csv")}
            >
              <Download size={14} /> {downloading === "csv" ? "…" : "Download CSV report"}
            </button>
          </div>
        </Popover>
      )}
    </>
  );
}
