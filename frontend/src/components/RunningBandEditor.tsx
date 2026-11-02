/**
 * Module: components/RunningBandEditor
 *
 * The editor of one header or footer of a page style: what it prints in an invisible three-column table (left, centre
 * and right cells), an optional logo, and whether the first page shows it. One editor serves the text view's page setup
 * dialog (for the layout and for each page style) and the Blocks view's layout settings, so a header looks and behaves
 * the same everywhere.
 *
 * Responsibilities:
 * - Choose between "inherit" (a page style takes the layout's; the layout takes a page number), "its own text"
 *   and "nothing" (an explicitly empty band), and write the band back (`undefined`, an object, `{}`).
 * - Edit the three cells (up to three lines each) and add a placeholder at the caret of the cell last edited; the page
 *   number, total pages and "Page X of Y" are always offered, with a sample of what a cell prints.
 * - Choose the logo from the layout tier's image library, its height and its cell, through the shared `ReportImageField`.
 * - Set the band's font, size and colour through the shared font and colour fields (the three cells share one setting), and
 *   mark the selected words bold or italic (`**` and `*`, the marks the server reads).
 * - Say how much of the margin the band takes and warn when it does not fit, using the same arithmetic the server checks.
 *
 * Design decisions: the editor edits the band it is given and never judges it (the server checks names, placeholders and
 * fit and the designer shows its problems). Without an image library (a story or a read-only view) the logo is shown
 * but not editable.
 */
import { useRef, useState, type SyntheticEvent } from "react";

import type { ReportFontChoice, ReportImageLibrary } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { DEFAULT_COLOUR_CONTEXT, type ColourContext, type ColourEntry } from "../utils/reportColours";
import { STANDARD_FONT_CHOICES } from "../utils/reportFonts";
import {
  BAND_FIRST_PAGE, BAND_SIZE_PT, BAND_SLOTS, DEFAULT_LOGO_CM, MAX_BAND_SIZE_PT, MAX_LOGO_CM, MIN_BAND_SIZE_PT, MIN_LOGO_CM, bandNeedsCm,
  insertAtCaret, pageSample, wrapMark, type BandSlot, type RunningBand,
} from "../utils/reportPageSetup";
import { ColourChoiceField } from "./ColourChoiceField";
import { FontChoiceField } from "./FontChoiceField";
import { TextAreaField, TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { ReportImageField } from "./ReportImageField";

/** The placeholders a header or footer can name besides the layout's own variables. */
export const BAND_PLACEHOLDERS = [
  "report_title", "project_name", "project_code", "organisation", "generated_on", "layout_version", "org.footer_text", "page", "pages",
] as const;

/** Insert choices that are page fields, which exist only in a header or footer: the value is the choice, `snippet` what is written. */
const PAGE_CHOICES = [
  { value: "page", snippet: "{{page}}" },
  { value: "pages", snippet: "{{pages}}" },
  { value: "page_of_pages", snippet: "Page {{page}} of {{pages}}" },
] as const;
const PAGE_FIELD_NAMES = new Set(["page", "pages"]);

/** What the font and colour fields offer: the fonts the server gives authors, the colour scheme and the layout's own palette. */
export interface BandLook {
  fonts?: ReportFontChoice[];
  colours?: ColourContext;
  palette?: ColourEntry[];
}

type Mode = "inherit" | "custom" | "none";

function modeOf(value: RunningBand | undefined): Mode {
  if (value === undefined) return "inherit";
  return Object.keys(value).length === 0 ? "none" : "custom";
}

/**
 * @param kind Whether this is the header or the footer.
 * @param value The band, `undefined` to inherit or `{}` for none.
 * @param onChange Called with the band after any edit.
 * @param inheritFrom What an unset band takes: the default, a page number (`template`, for the layout itself) or the layout's (`layout`, for a page style).
 * @param margin The margin in cm the band must fit (the top for a header, the bottom for a footer).
 * @param placeholders The global placeholder names offered for insertion; the page fields are added by the editor whatever this holds.
 * @param images The picture library a logo is chosen from, and where an upload goes (absent: the logo cannot be changed).
 * @param look The fonts and colours the font and colour fields offer (the standard ones when absent).
 * @param disabled Whether the editor is read-only.
 */
export function RunningBandEditor({
  kind, value, onChange, inheritFrom, margin, placeholders = BAND_PLACEHOLDERS, images, look = {}, disabled = false,
}: {
  kind: "header" | "footer";
  value: RunningBand | undefined;
  onChange: (next: RunningBand | undefined) => void;
  inheritFrom: "template" | "layout";
  margin: number;
  placeholders?: readonly string[];
  images?: { library: ReportImageLibrary; scope: "organization" | "project" };
  look?: BandLook;
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
  const caret = useRef<Partial<Record<BandSlot, { start: number; end: number }>>>({});
  const cells = useRef<Partial<Record<BandSlot, HTMLTextAreaElement>>>({});
  const insert = (choice: string) => {
    if (!choice) return;
    const page = PAGE_CHOICES.find((entry) => entry.value === choice);
    const current = band[lastCell] ?? "";
    const at = caret.current[lastCell] ?? { start: current.length, end: current.length };
    const next = insertAtCaret(current, page ? page.snippet : `{{${choice}}}`, at.start, at.end);
    caret.current[lastCell] = { start: next.caret, end: next.caret };
    set({ [lastCell]: next.text });
  };
  /** Wraps the selection of the cell last edited in `marker`, and puts the selection back on the wrapped words. */
  const mark = (marker: string) => {
    const current = band[lastCell] ?? "";
    const at = caret.current[lastCell] ?? { start: current.length, end: current.length };
    const next = wrapMark(current, marker, at.start, at.end);
    caret.current[lastCell] = { start: next.start, end: next.end };
    set({ [lastCell]: next.text });
    // Put the selection back on the wrapped words once the new text is in the cell, so the next press acts on what the author sees.
    const cell = lastCell;
    requestAnimationFrame(() => {
      cells.current[cell]?.focus();
      cells.current[cell]?.setSelectionRange(next.start, next.end);
    });
  };
  // The caret is read on every selection change and on leaving the cell (the Insert list takes the focus), so it survives the move.
  const remember = (slot: BandSlot) => (e: SyntheticEvent<HTMLTextAreaElement>) => {
    cells.current[slot] = e.currentTarget;
    caret.current[slot] = { start: e.currentTarget.selectionStart, end: e.currentTarget.selectionEnd };
  };
  const choices = [
    ...PAGE_CHOICES.map((entry) => ({ value: entry.value, label: text.pageChoiceLabels[entry.value] })),
    ...placeholders.filter((name) => !PAGE_FIELD_NAMES.has(name)).map((name) => ({ value: name, label: `{{${name}}}` })),
  ];
  const fonts = look.fonts ?? STANDARD_FONT_CHOICES;
  const generic = fonts.find((f) => f.key === (band.font ?? ""))?.generic;
  const sampleStyle = {
    margin: 0, color: band.colour && /^#[0-9a-fA-F]{6}$/.test(band.colour) ? band.colour : "var(--color-text-muted)",
    fontFamily: generic, fontSize: `${band.size ?? BAND_SIZE_PT}pt`,
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
                  inputProps={{ onSelect: remember(slot), onBlur: remember(slot) }}
                />
                {pageSample(band[slot] ?? "") !== null && (
                  <p style={sampleStyle}>
                    <span className="text-muted" style={{ fontFamily: "inherit" }}>{text.sample} </span>
                    {(pageSample(band[slot] ?? "") ?? []).map((run, i) => (
                      <span key={i} style={{ fontWeight: run.bold ? "bold" : undefined, fontStyle: run.italic ? "italic" : undefined }}>{run.text}</span>
                    ))}
                  </p>
                )}
              </div>
            ))}
          </div>
          {!disabled && (
            <div className="row" style={{ alignItems: "flex-end", gap: "var(--space-3)", flexWrap: "wrap" }}>
              <LabeledSelect
                label={text.insertLabel} value="" placeholder={text.insertChoose} help={strings.help.bandPlaceholder}
                options={choices} onChange={insert}
              />
              <div role="group" aria-label={text.marksAria(title)} className="row" style={{ gap: "var(--space-1)" }}>
                <button type="button" className="btn btn-sm" aria-label={`${title}: ${text.boldButton}`} onClick={() => mark("**")}>
                  <strong>B</strong>
                </button>
                <button type="button" className="btn btn-sm" aria-label={`${title}: ${text.italicButton}`} onClick={() => mark("*")}>
                  <em>I</em>
                </button>
              </div>
            </div>
          )}
          <div className="row" style={{ alignItems: "flex-end", gap: "var(--space-3)", flexWrap: "wrap" }}>
            <FontChoiceField
              label={`${title}: ${text.fontLabel.toLowerCase()}`} value={band.font} fonts={fonts} disabled={disabled} help={strings.help.bandFont}
              emptyLabel={text.fontDefault} onChange={(key) => set({ font: key || undefined })}
            />
            <div style={{ width: "7rem" }}>
              <TextField
                label={`${title}: ${text.sizeLabel.toLowerCase()}`} value={band.size === undefined ? "" : String(band.size)} disabled={disabled}
                help={strings.help.bandSize} placeholder={text.sizeDefault} inputProps={{ type: "number", min: MIN_BAND_SIZE_PT, max: MAX_BAND_SIZE_PT, step: 0.5 }}
                onChange={(input) => set({ size: input.trim() === "" || Number.isNaN(Number(input)) ? undefined : Number(input) })}
              />
            </div>
            <ColourChoiceField
              label={`${title}: ${text.colourLabel.toLowerCase()}`} value={band.colour ?? ""} disabled={disabled} help={strings.help.bandColour}
              context={look.colours ?? DEFAULT_COLOUR_CONTEXT} layoutPalette={look.palette ?? []} allowNone={false}
              emptyLabel={text.colourDefault} onChange={(colour) => set({ colour: colour || undefined })}
            />
          </div>
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
