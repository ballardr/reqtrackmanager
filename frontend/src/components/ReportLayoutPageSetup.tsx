/**
 * Module: components/ReportLayoutPageSetup
 *
 * The text view's page setup: a settings button beside the block toolbar that opens a dialog with the layout's paper,
 * orientation, margins, mirrored margins and named page styles, and writes them into the text (`@layout document
 * landscape A3 mirror margins top=2` and one `@pagestyle` line per style).
 *
 * Responsibilities: arrange it in the shared setting groups (`LayoutSettingGroup`: Page, Margins, Header, Footer, Look (the table heading colours), Tables and
 * Page styles, each collapsible and marked when it holds a non-default value), read the setup from the text (`readPageSetup`), draw it with the shared page-setup fields and
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
import { anySettingChanged, marginsGroupSummary, pageGroupSummary, pageSetupChanges } from "../utils/reportLayoutSettingGroups";
import { DEFAULT_MARGIN_CM, PAGE_ORIENTATIONS, PAGE_SIZES, readPageSetup, readPalette, writePageSetup, type PageSetup } from "../utils/reportPageSetup";
import { CheckboxField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { LayoutSettingGroup } from "./LayoutSettingGroup";
import { Modal } from "./Modal";
import { PageMarginsFields } from "./PageMarginsFields";
import { PageOutline } from "./PageOutline";
import { PageStylesEditor } from "./PageStylesEditor";
import { TableHeadingColours } from "./TableHeadingColours";
import { RunningBandEditor, type BandLook } from "./RunningBandEditor";
import { Tooltip } from "./Tooltip";

/**
 * @param text The layout text; its header, `@header`, `@footer` and `@pagestyle` lines are rewritten on a change.
 * @param onChange Called with the new text.
 * @param images The picture library a header or footer logo is chosen from (absent: logos cannot be changed here).
 * @param placeholders The placeholder names a header or footer offers.
 * @param look The fonts and colours a header or footer's font and colour fields offer (the layout's own palette is read from `text`).
 * @param newLayout Whether the layout is new (Page and Margins then start open).
 */
export function ReportLayoutPageSetup({
  text, onChange, images, placeholders, look, newLayout = false,
}: {
  text: string;
  onChange: (text: string) => void;
  images?: { library: ReportImageLibrary; scope: "organization" | "project" };
  placeholders?: readonly string[];
  look?: Omit<BandLook, "palette">;
  newLayout?: boolean;
}) {
  const strings = useStrings();
  const labels = strings.pageSetup;
  const [open, setOpen] = useState(false);
  const setup = readPageSetup(text);
  if (setup === null) return null;
  const bandLook: BandLook = { ...look, palette: readPalette(text) };
  const set = (patch: Partial<PageSetup>) => onChange(writePageSetup(text, { ...setup, ...patch }));
  const changes = pageSetupChanges(setup);
  const marked = anySettingChanged(changes);
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
            <LayoutSettingGroup
              group="page" changed={changes.page} newLayout={newLayout}
              summary={pageGroupSummary(setup.size, setup.orientation, setup.mirror, {
                orientation: (o) => labels.orientationLabels[o].toLowerCase(), mirrored: labels.pageSummaryMirrored,
              })}
            >
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
            </LayoutSettingGroup>
            <LayoutSettingGroup
              group="margins" changed={changes.margins} newLayout={newLayout}
              summary={marginsGroupSummary(setup.margins, { all: labels.marginsSummaryAll, sides: labels.marginsSummarySides })}
            >
              <PageMarginsFields value={setup.margins} mirror={setup.mirror} onChange={(margins) => set({ margins })} />
            </LayoutSettingGroup>
            {(["header", "footer"] as const).map((kind) => (
              <LayoutSettingGroup key={kind} group={kind} changed={changes[kind]}>
                {kind === "header" && <p style={{ margin: 0, color: "var(--color-text-muted)" }}>{labels.band.intro}</p>}
                <RunningBandEditor
                  kind={kind} value={setup[kind]} inheritFrom="template" images={images} placeholders={placeholders} look={bandLook}
                  margin={(kind === "header" ? setup.margins.top : setup.margins.bottom) ?? DEFAULT_MARGIN_CM}
                  onChange={(next) => set({ [kind]: next })}
                />
              </LayoutSettingGroup>
            ))}
            <LayoutSettingGroup group="look" changed={changes.look}>
              <TableHeadingColours
                value={setup.tableHeadings ?? {}} colours={look?.colours} palette={bandLook.palette}
                onChange={(tableHeadings) => set({ tableHeadings })}
              />
            </LayoutSettingGroup>
            <LayoutSettingGroup group="tables" changed={changes.tables}>
              <CheckboxField
                label={labels.repeatHeaderLabel} help={strings.help.layoutRepeatTableHeader} checked={setup.repeatHeader !== false}
                onChange={(on) => set({ repeatHeader: on ? undefined : false })}
              />
              <CheckboxField
                label={labels.alignTablesLabel} help={strings.help.layoutAlignTables} checked={setup.alignTables !== false}
                onChange={(on) => set({ alignTables: on ? undefined : false })}
              />
            </LayoutSettingGroup>
            <LayoutSettingGroup group="styles" changed={changes.styles}>
              <PageStylesEditor
                images={images} placeholders={placeholders} look={bandLook}
                value={setup.styles} onChange={(styles) => set({ styles })}
                base={{ size: setup.size, orientation: setup.orientation, margins: setup.margins, mirror: setup.mirror }}
              />
            </LayoutSettingGroup>
          </div>
        </Modal>
      )}
    </>
  );
}
