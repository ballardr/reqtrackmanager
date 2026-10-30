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

import type { ReportImageLibrary } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { DEFAULT_MARGIN_CM, PAGE_ORIENTATIONS, PAGE_SIZES, readPageSetup, writePageSetup, type PageSetup } from "../utils/reportPageSetup";
import { CheckboxField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { PageMarginsFields } from "./PageMarginsFields";
import { PageOutline } from "./PageOutline";
import { PageStylesEditor } from "./PageStylesEditor";
import { RunningBandEditor } from "./RunningBandEditor";
import { Tooltip } from "./Tooltip";

/**
 * @param text The layout text; its header, `@header`, `@footer` and `@pagestyle` lines are rewritten on a change.
 * @param onChange Called with the new text.
 * @param images The picture library a header or footer logo is chosen from (absent: logos cannot be changed here).
 * @param placeholders The placeholder names a header or footer offers.
 */
export function ReportLayoutPageSetup({
  text, onChange, images, placeholders,
}: {
  text: string;
  onChange: (text: string) => void;
  images?: { library: ReportImageLibrary; scope: "organization" | "project" };
  placeholders?: readonly string[];
}) {
  const strings = useStrings();
  const labels = strings.pageSetup;
  const [open, setOpen] = useState(false);
  const setup = readPageSetup(text);
  if (setup === null) return null;
  const set = (patch: Partial<PageSetup>) => onChange(writePageSetup(text, { ...setup, ...patch }));
  const marked = setup.orientation !== "portrait" || setup.size !== "A4" || setup.mirror || setup.repeatHeader === false
    || Object.keys(setup.margins).length > 0 || setup.styles.length > 0 || setup.header !== undefined || setup.footer !== undefined;
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
              <CheckboxField
                label={labels.repeatHeaderLabel} help={strings.help.layoutRepeatTableHeader} checked={setup.repeatHeader !== false}
                onChange={(on) => set({ repeatHeader: on ? undefined : false })}
              />
            </div>
            <h3 style={{ margin: 0 }}>{labels.marginsTitle}</h3>
            <PageMarginsFields value={setup.margins} mirror={setup.mirror} onChange={(margins) => set({ margins })} />
            <h3 style={{ margin: 0 }}>{labels.band.sectionTitle}</h3>
            <p style={{ margin: 0, color: "var(--color-text-muted)" }}>{labels.band.intro}</p>
            {(["header", "footer"] as const).map((kind) => (
              <RunningBandEditor
                key={kind} kind={kind} value={setup[kind]} inheritFrom="template" images={images} placeholders={placeholders}
                margin={(kind === "header" ? setup.margins.top : setup.margins.bottom) ?? DEFAULT_MARGIN_CM}
                onChange={(next) => set({ [kind]: next })}
              />
            ))}
            <h3 style={{ margin: 0 }}>{labels.stylesTitle}</h3>
            <PageStylesEditor
              images={images} placeholders={placeholders}
              value={setup.styles} onChange={(styles) => set({ styles })}
              base={{ size: setup.size, orientation: setup.orientation, margins: setup.margins, mirror: setup.mirror }}
            />
          </div>
        </Modal>
      )}
    </>
  );
}
