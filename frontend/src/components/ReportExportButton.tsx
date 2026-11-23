/**
 * Module: components/ReportExportButton
 *
 * The "report export trigger" pattern (`docs/ux-style-guide.md`): a single "Export" button that opens a `Popover`
 * offering "Download PDF report" / "Download Word report" / "Download CSV report", for a host page or panel whose
 * report generation needs no configuration screen of its own (contrast `pages/ReportsPage.tsx`). Shared by the
 * compliance dashboards and panels so none shows two permanently visible adjacent buttons (Principle 11).
 *
 * The host owns error handling: `onDownload` catches and surfaces its own failure toast, naming what failed to
 * generate. This component only tracks which kind is mid-download, to disable the trigger while the file is
 * produced (as `CsvImportWizard.tsx`'s `exporting`). The offered formats are the shared `ActionMenuList` (text rows).
 */
import { Download } from "lucide-react";
import { useRef, useState } from "react";
import type { ReactNode } from "react";

import { REPORT_FORMAT } from "../api/reportFormats";
import type { ReportFileKind } from "../api/reports";
import { ActionMenuList, type ActionMenuItem } from "./ActionMenu";
import { Popover } from "./Popover";

/**
 * `kinds` lists the formats on offer (default PDF and CSV, what the compliance
 * callers have); `label` renames the trigger when it sits beside a primary
 * download button ("More formats") rather than standing alone. `extras` adds
 * related downloads that are not a format of the report (a list's import
 * template) under the formats, and `note` is one muted line under them (columns
 * the personal-data policy left out). `disabled` holds the trigger back while the host cannot produce a file.
 */
export function ReportExportButton<K extends ReportFileKind = "pdf" | "csv">({
  onDownload,
  kinds = ["pdf", "csv"] as K[],
  label = "Export",
  extras = [],
  note,
  disabled = false,
}: {
  onDownload: (kind: K) => Promise<void>;
  kinds?: readonly K[];
  label?: string;
  extras?: readonly { key: string; label: string; onSelect: () => void | Promise<void> }[];
  note?: ReactNode;
  /** True to disable the trigger (the host is not ready to produce a file). */
  disabled?: boolean;
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
      <button ref={triggerRef} type="button" className="btn" disabled={disabled} onClick={() => setMenuOpen((v) => !v)}>
        <Download /> {downloading ? "Exporting…" : label}
      </button>
      {menuOpen && (
        <Popover anchorRef={triggerRef} fit menu title="Export" onClose={() => setMenuOpen(false)}>
          <ActionMenuList
            label="Export"
            footer={note}
            onSelect={() => setMenuOpen(false)}
            items={[
              ...kinds.map((kind): ActionMenuItem => ({
                key: kind,
                icon: <Download aria-hidden="true" />,
                label: `Download ${REPORT_FORMAT[kind].label} report`,
                title: REPORT_FORMAT[kind].title,
                disabled: downloading !== null,
                onSelect: () => void handleDownload(kind),
              })),
              ...extras.map((extra): ActionMenuItem => ({
                key: extra.key,
                icon: <Download aria-hidden="true" />,
                label: extra.label,
                disabled: downloading !== null,
                onSelect: () => void extra.onSelect(),
              })),
            ]}
          />
        </Popover>
      )}
    </>
  );
}
