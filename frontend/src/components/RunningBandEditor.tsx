/**
 * Module: components/RunningBandEditor
 *
 * The editor of one header or footer of a page style: what it prints in an invisible three-column table (left, centre
 * and right cells), an optional logo, and whether the first page shows it. One editor serves the text view's page setup
 * dialog (for the layout and for each page style) and the Blocks view's layout settings, so a header looks and behaves
 * the same everywhere.
 *
 * Responsibilities:
 * - Choose between "inherit" (a page style takes the layout's; the layout takes the report template's), "its own text"
 *   and "nothing" (an explicitly empty band), and write the band back (`undefined`, an object, `{}`).
 * - Edit the three cells (up to three lines each) and add a placeholder to the cell last edited.
 * - Choose the logo from the layout tier's image library, its height and its cell, through the shared `ReportImageField`.
 * - Say how much of the margin the band takes and warn when it does not fit, using the same arithmetic the server checks.
 *
 * Design decisions: the editor edits the band it is given and never judges it (the server checks names, placeholders and
 * fit and the designer shows its problems). Without an image library (a story or a read-only view) the logo is shown
 * but not editable.
 */
import { useState } from "react";

import type { ReportImageLibrary } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import {
  BAND_FIRST_PAGE, BAND_SLOTS, DEFAULT_LOGO_CM, MAX_LOGO_CM, MIN_LOGO_CM, bandNeedsCm, type BandSlot, type RunningBand,
} from "../utils/reportPageSetup";
import { TextAreaField, TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { ReportImageField } from "./ReportImageField";

/** The placeholders a header or footer can name besides the layout's own variables. */
export const BAND_PLACEHOLDERS = [
  "report_title", "project_name", "project_code", "organisation", "generated_on", "layout_version", "page", "pages",
] as const;

type Mode = "inherit" | "custom" | "none";

function modeOf(value: RunningBand | undefined): Mode {
  if (value === undefined) return "inherit";
  return Object.keys(value).length === 0 ? "none" : "custom";
}

/**
 * @param kind Whether this is the header or the footer.
 * @param value The band, `undefined` to inherit or `{}` for none.
 * @param onChange Called with the band after any edit.
 * @param inheritFrom What an unset band takes: the report template's (for the layout itself) or the layout's (for a page style).
 * @param margin The margin in cm the band must fit (the top for a header, the bottom for a footer).
 * @param placeholders The placeholder names offered for insertion.
 * @param images The picture library a logo is chosen from, and where an upload goes (absent: the logo cannot be changed).
 * @param disabled Whether the editor is read-only.
 */
export function RunningBandEditor({
  kind, value, onChange, inheritFrom, margin, placeholders = BAND_PLACEHOLDERS, images, disabled = false,
}: {
  kind: "header" | "footer";
  value: RunningBand | undefined;
  onChange: (next: RunningBand | undefined) => void;
  inheritFrom: "template" | "layout";
  margin: number;
  placeholders?: readonly string[];
  images?: { library: ReportImageLibrary; scope: "organization" | "project" };
  disabled?: boolean;
}) {
  const strings = useStrings();
  const text = strings.pageSetup.band;
  const title = kind === "header" ? text.headerTitle : text.footerTitle;
  const noun = title.toLowerCase();
  const [lastCell, setLastCell] = useState<BandSlot>("left");
  const mode = modeOf(value);
  const band = value ?? {};
  const set = (patch: Partial<RunningBand>) => onChange({ ...band, ...patch });
  const needs = bandNeedsCm(value);
  const side = kind === "header" ? "top" : "bottom";
  const logo = band.logo;
  const setMode = (next: string) => {
    if (next === "inherit") onChange(undefined);
    else if (next === "none") onChange({});
    else onChange({ left: "" });
  };
  const removeLogo = () => {
    const next = { ...band };
    delete next.logo;
    // A band with nothing left in it would read as "nothing", so keep it as an empty left cell.
    onChange(Object.keys(next).length === 0 ? { left: "" } : next);
  };
  const insert = (name: string) => {
    if (name) set({ [lastCell]: `${band[lastCell] ?? ""}{{${name}}}` });
  };
  return (
    <div role="group" aria-label={title} className="stack" style={{ gap: "var(--space-2)" }}>
      <LabeledSelect
        label={`${title}: ${text.modeLabel.toLowerCase()}`} value={mode} disabled={disabled} placeholder={null} help={strings.help.bandMode}
        options={[
          { value: "inherit", label: inheritFrom === "template" ? text.modeInheritDocument : text.modeInheritStyle },
          { value: "custom", label: text.modeCustom },
          { value: "none", label: text.modeNone },
        ]}
        onChange={setMode}
      />
      {mode === "custom" && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(10rem, 1fr))", gap: "var(--space-3)" }}>
            {BAND_SLOTS.map((slot) => (
              <div key={slot} onFocus={() => setLastCell(slot)}>
                <TextAreaField
                  label={text.cellLabels[slot]} ariaLabel={text.cellAria(title, text.cellLabels[slot])} value={band[slot] ?? ""}
                  disabled={disabled} help={strings.help.bandCell} onChange={(next) => set({ [slot]: next })}
                />
              </div>
            ))}
          </div>
          {!disabled && (
            <LabeledSelect
              label={text.insertLabel} value="" placeholder={text.insertChoose} help={strings.help.bandPlaceholder}
              options={placeholders.map((name) => ({ value: name, label: `{{${name}}}` }))} onChange={insert}
            />
          )}
          {images ? (
            <div className="row" style={{ alignItems: "flex-end", gap: "var(--space-3)", flexWrap: "wrap" }}>
              <ReportImageField
                label={`${title} ${text.logoLabel.toLowerCase()}`} value={logo?.file ?? ""} library={images.library} scope={images.scope}
                disabled={disabled} help={strings.help.bandLogo}
                onChange={(file) => set({ logo: { ...(logo ?? { height: DEFAULT_LOGO_CM }), file } })}
              />
              {logo && (
                <>
                  <div style={{ width: "8rem" }}>
                    <TextField
                      label={text.logoHeightLabel} value={String(logo.height)} disabled={disabled} help={strings.help.bandLogoHeight}
                      inputProps={{ type: "number", min: MIN_LOGO_CM, max: MAX_LOGO_CM, step: 0.1 }}
                      onChange={(input) => set({ logo: { ...logo, height: Number(input) } })}
                    />
                  </div>
                  <LabeledSelect
                    label={text.logoSlotLabel} value={logo.slot ?? "left"} disabled={disabled} placeholder={null} help={strings.help.bandLogoSlot}
                    options={BAND_SLOTS.map((slot) => ({ value: slot, label: text.cellLabels[slot] }))}
                    onChange={(slot) => set({ logo: { ...logo, slot: slot as BandSlot } })}
                  />
                  {!disabled && (
                    <button
                      type="button" className="btn btn-sm" aria-label={`${text.removeLogo} (${noun})`}
                      onClick={removeLogo}
                    >
                      {text.removeLogo}
                    </button>
                  )}
                </>
              )}
            </div>
          ) : (
            logo && <p style={{ margin: 0, color: "var(--color-text-muted)" }}>{text.imagesUnavailable}</p>
          )}
          <LabeledSelect
            label={`${title}: ${text.firstPageLabel.toLowerCase()}`} value={band.first_page ?? "same"} disabled={disabled} placeholder={null}
            help={strings.help.bandFirstPage}
            options={BAND_FIRST_PAGE.map((choice) => ({ value: choice, label: choice === "same" ? text.firstPageSame : text.firstPageNone }))}
            onChange={(choice) => set({ first_page: choice === "none" ? "none" : undefined })}
          />
        </>
      )}
      {needs > 0 && (
        needs > margin + 1e-9
          ? <p role="alert" style={{ margin: 0, color: "var(--color-danger)" }}>{text.needs(noun, side, needs.toFixed(1), String(margin))}</p>
          : <p style={{ margin: 0, color: "var(--color-text-muted)" }}>{text.fits(noun, needs.toFixed(1))}</p>
      )}
    </div>
  );
}
