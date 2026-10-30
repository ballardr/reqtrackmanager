/**
 * Module: components/ReportLayoutPageSetup
 *
 * The text view's page setup: a settings button beside the block toolbar that opens a dialog with the layout's paper,
 * orientation, margins, mirrored margins and named page styles, and writes them into the text (`@layout document
 * landscape A3 mirror margins top=2` and one `@pagestyle` line per style).
 *
 * Responsibilities: read the setup from the text (`readPageSetup`), draw it with the shared page-setup fields and
 * rewrite exactly those lines on a change (`writePageSetup`). The server's parser stays the judge of the text. A table
 * layout has no pages, so it renders nothing.
 *
 * Design decisions: changes apply as they are made (there is no Save to press, as in the other settings popovers), so
 * the dialog's close button is the only action.
 */
import { Settings } from "lucide-react";
import { useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { PAGE_ORIENTATIONS, PAGE_SIZES, readPageSetup, writePageSetup, type PageSetup } from "../utils/reportPageSetup";
import { CheckboxField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { PageMarginsFields } from "./PageMarginsFields";
import { PageOutline } from "./PageOutline";
import { PageStylesEditor } from "./PageStylesEditor";
import { Tooltip } from "./Tooltip";

/**
 * @param text The layout text; its header and `@pagestyle` lines are rewritten on a change.
 * @param onChange Called with the new text.
 */
export function ReportLayoutPageSetup({ text, onChange }: { text: string; onChange: (text: string) => void }) {
  const strings = useStrings();
  const labels = strings.pageSetup;
  const [open, setOpen] = useState(false);
  const setup = readPageSetup(text);
  if (setup === null) return null;
  const set = (patch: Partial<PageSetup>) => onChange(writePageSetup(text, { ...setup, ...patch }));
  const marked = setup.orientation !== "portrait" || setup.size !== "A4" || setup.mirror
    || Object.keys(setup.margins).length > 0 || setup.styles.length > 0;
  const label = strings.reportLayouts.pageSetupLabel(labels.orientationLabels[setup.orientation], setup.size);
  return (
    <>
      <Tooltip label={label}>
        <button
          type="button" className={`btn btn-sm btn-icon${marked ? " btn-marked" : ""}`} aria-label={label}
          aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}
        >
          <Settings size={14} aria-hidden="true" />
        </button>
      </Tooltip>
      {open && (
        <Modal title={labels.title} size="lg" onClose={() => setOpen(false)}>
          <div className="stack">
            <div className="row" style={{ alignItems: "flex-end", gap: "var(--space-3)" }}>
              <PageOutline size={setup.size} orientation={setup.orientation} margins={setup.margins} mirror={setup.mirror} />
              <LabeledSelect
                label={labels.sizeLabel} help={strings.help.layoutPageSize} value={setup.size} placeholder={null}
                onChange={(size) => set({ size: size as PageSetup["size"] })}
                options={PAGE_SIZES.map((size) => ({ value: size, label: size }))}
              />
              <LabeledSelect
                label={labels.orientationLabel} help={strings.help.layoutOrientation} value={setup.orientation} placeholder={null}
                onChange={(orientation) => set({ orientation: orientation as PageSetup["orientation"] })}
                options={PAGE_ORIENTATIONS.map((value) => ({ value, label: labels.orientationLabels[value] }))}
              />
              <CheckboxField
                label={labels.mirrorLabel} help={strings.help.layoutMirrorMargins} checked={setup.mirror}
                onChange={(mirror) => set({ mirror })}
              />
            </div>
            <h3 style={{ margin: 0 }}>{labels.marginsTitle}</h3>
            <PageMarginsFields value={setup.margins} mirror={setup.mirror} onChange={(margins) => set({ margins })} />
            <h3 style={{ margin: 0 }}>{labels.stylesTitle}</h3>
            <PageStylesEditor
              value={setup.styles} onChange={(styles) => set({ styles })}
              base={{ size: setup.size, orientation: setup.orientation, margins: setup.margins, mirror: setup.mirror }}
            />
          </div>
        </Modal>
      )}
    </>
  );
}
