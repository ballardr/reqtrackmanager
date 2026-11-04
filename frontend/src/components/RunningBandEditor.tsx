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
 * - Edit the three cells, stacked one above the other at the full width of the editor (up to three lines each). A cell's
 *   gear opens a popover with its fixed width (blank: it fits its text) and vertical alignment (blank: the band's), and a
 *   summary of both shows beside its title, with a [+] menu that writes a placeholder at that cell's caret (grouped Page, Report,
 *   Project, Organisation and Other, each with a sample; the page number, total pages and "Page X of Y" are always offered) and
 *   Bold and Italic buttons for that cell.
 * - Say how much of the margin the band takes and warn when it does not fit, using the same arithmetic the server checks;
 *   the message stays visible with the "More" group closed.
 * - In a closed-by-default "More" group (its bar counts what is set): choose the logo from the layout tier's image library, its
 *   height and its cell, through the shared `ReportImageField`; set the band's font, size and colour through the shared font
 *   and colour fields (the three cells share one setting); the band's vertical alignment and the first-page choice.
 * - Mark the selected words of a cell bold or italic (`**` and `*`, the marks the server reads).
 *
 * Design decisions: the editor edits the band it is given and never judges it (the server checks names, placeholders and
 * fit and the designer shows its problems). Without an image library (a story or a read-only view) the logo is shown
 * but not editable.
 */
import { Plus } from "lucide-react";

import type { ReportFontChoice, ReportImageLibrary } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { useTextSelections } from "../hooks/useTextSelections";
import { DEFAULT_COLOUR_CONTEXT, type ColourContext, type ColourEntry } from "../utils/reportColours";
import { STANDARD_FONT_CHOICES } from "../utils/reportFonts";
import {
  BAND_DEFAULT_VALIGN, BAND_FIRST_PAGE, BAND_SIZE_PT, BAND_SLOTS, BAND_VALIGN, DEFAULT_LOGO_CM, MAX_BAND_SIZE_PT, MAX_LOGO_CM, MIN_BAND_SIZE_PT, MIN_LOGO_CM, bandMoreChanges,
  bandNeedsCm, pageSample, type BandSlot, type RunningBand,
} from "../utils/reportPageSetup";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { CollapsibleSection } from "./CollapsibleSection";
import { ColourChoiceField } from "./ColourChoiceField";
import { FontChoiceField } from "./FontChoiceField";
import { TextAreaField, TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { MarkButtons } from "./MarkButtons";
import { ReportImageField } from "./ReportImageField";
import { SettingsPopoverButton } from "./SettingsPopoverButton";

/** The placeholders a header or footer can name besides the layout's own variables. */
export const BAND_PLACEHOLDERS = [
  "report_title", "project_name", "project_report_name", "project_code", "organisation", "generated_on", "layout_version", "org.footer_text", "page", "pages",
] as const;

/** Insert choices that are page fields, which exist only in a header or footer: the value is the choice, `snippet` what is written. */
const PAGE_CHOICES = [
  { value: "page", snippet: "{{page}}" },
  { value: "pages", snippet: "{{pages}}" },
  { value: "page_of_pages", snippet: "Page {{page}} of {{pages}}" },
] as const;
const PAGE_FIELD_NAMES = new Set(["page", "pages"]);
type PlaceholderGroup = "report" | "project" | "organisation" | "other";
const PLACEHOLDER_GROUP_ORDER: readonly PlaceholderGroup[] = ["report", "project", "organisation", "other"];
/** Which group of the placeholder menu a name sits in; a name not listed (a layout's own) goes to "Other". */
const PLACEHOLDER_GROUP: Record<string, PlaceholderGroup> = {
  report_title: "report", generated_on: "report", layout_version: "report",
  project_name: "project", project_report_name: "project", project_code: "project",
  organisation: "organisation", "org.footer_text": "organisation",
};

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
  const mode = modeOf(value);
  const band = value ?? {};
  const set = (patch: Partial<RunningBand>) => onChange({ ...band, ...patch });
  const needs = bandNeedsCm(value);
  const side = kind === "header" ? "top" : "bottom";
  const defaultValign = BAND_DEFAULT_VALIGN[kind];
  const logo = band.logo;
  const moreChanged = bandMoreChanges(value);
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
  const { remember, mark, insert: insertText } = useTextSelections<BandSlot>();
  /** Writes a placeholder over the selection of one cell, and puts the caret after it once the new text is in the cell. */
  const insert = (slot: BandSlot, choice: string) => {
    const page = PAGE_CHOICES.find((entry) => entry.value === choice);
    insertText(slot, band[slot] ?? "", page ? page.snippet : `{{${choice}}}`, (next) => set({ [slot]: next }));
  };
  /** The names after the page fields, kept in group order so each group's heading shows once. */
  const named = placeholders
    .filter((name) => !PAGE_FIELD_NAMES.has(name))
    .map((name) => ({ name, group: PLACEHOLDER_GROUP[name] ?? "other" }))
    .sort((a, b) => PLACEHOLDER_GROUP_ORDER.indexOf(a.group) - PLACEHOLDER_GROUP_ORDER.indexOf(b.group));
  /** The placeholder menu: the page fields first, then the names the layout offers, grouped and each with a sample of what it prints. */
  const menuItems = (slot: BandSlot): ActionMenuItem[] => [
    ...PAGE_CHOICES.map((entry) => ({
      key: entry.value, label: text.pageChoiceLabels[entry.value], group: text.placeholderGroups.page, hint: text.placeholderSamples[entry.value],
      onSelect: () => insert(slot, entry.value),
    })),
    ...named.map(({ name, group }) => ({
      key: name, label: text.placeholderLabels[name] ?? `{{${name}}}`, group: text.placeholderGroups[group], hint: text.placeholderSamples[name],
      onSelect: () => insert(slot, name),
    })),
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
          <div className="stack" style={{ gap: "var(--space-3)" }}>
            {BAND_SLOTS.map((slot) => {
              const cell = text.cellLabels[slot];
              const width = band[`${slot}_width`];
              const valign = band[`${slot}_valign`];
              const summary = text.cellSettingsSummary(width, valign ? text.valignChoices[valign] : undefined);
              return (
                <div key={slot}>
                  <TextAreaField
                    label={cell} ariaLabel={text.cellAria(title, cell)} value={band[slot] ?? ""}
                    disabled={disabled} help={strings.help.bandCell} onChange={(next) => set({ [slot]: next })}
                    inputProps={{ onSelect: remember(slot), onBlur: remember(slot) }}
                    labelExtra={(
                      <span className="row" style={{ gap: "var(--space-2)", marginLeft: "auto", alignItems: "center" }}>
                        {summary && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{summary}</span>}
                        {!disabled && (
                          <>
                            <ActionMenu
                              triggerLabel={text.insertInto(title, cell)} items={menuItems(slot)} icon={<Plus size={14} aria-hidden="true" />}
                              size="sm" footer={text.insertFooter}
                            />
                            <MarkButtons
                              nameOf={(name) => text.markCellAria(title, cell, name)}
                              onMark={(marker) => mark(slot, band[slot] ?? "", marker, (next) => set({ [slot]: next }))}
                            />
                          </>
                        )}
                        <SettingsPopoverButton
                          label={summary ? `${text.cellSettings(cell)}: ${summary}` : text.cellSettings(cell)} title={text.cellSettings(cell)}
                          marked={summary !== ""}
                        >
                          <div className="stack">
                            <TextField
                              label={`${cell} ${text.widthLabel.toLowerCase()}`} value={width ?? ""} disabled={disabled}
                              help={strings.help.bandCellWidth} placeholder={text.widthFits}
                              onChange={(input) => set({ [`${slot}_width`]: input.trim() === "" ? undefined : input })}
                            />
                            <LabeledSelect
                              label={`${cell} ${text.valignLabel.toLowerCase()}`} value={valign ?? ""} disabled={disabled}
                              placeholder={text.valignInherit} help={strings.help.bandCellValign}
                              options={BAND_VALIGN.map((choice) => ({ value: choice, label: text.valignChoices[choice] }))}
                              onChange={(choice) => set({ [`${slot}_valign`]: choice || undefined })}
                            />
                          </div>
                        </SettingsPopoverButton>
                      </span>
                    )}
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
              );
            })}
          </div>
        </>
      )}
      {needs > 0 && (
        needs > margin + 1e-9
          ? <p role="alert" style={{ margin: 0, color: "var(--color-danger)" }}>{text.needs(noun, side, needs.toFixed(1), String(margin))}</p>
          : <p style={{ margin: 0, color: "var(--color-text-muted)" }}>{text.fits(noun, needs.toFixed(1))}</p>
      )}
      {mode === "custom" && (
        <CollapsibleSection
          sectionKey={`layoutSettings:band${kind === "header" ? "Header" : "Footer"}More`} title={text.moreTitle(title)} variant="plain" defaultCollapsed
          summary={moreChanged > 0 ? strings.pageSetup.groupChanged(moreChanged) : undefined} marked={moreChanged > 0}
        >
          <div className="stack" style={{ gap: "var(--space-2)" }}>
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
              label={`${title}: ${text.valignLabel.toLowerCase()}`} value={band.valign ?? defaultValign} disabled={disabled} placeholder={null}
              help={strings.help.bandValign}
              options={BAND_VALIGN.map((choice) => ({
                value: choice, label: choice === defaultValign ? text.valignDefault(text.valignChoices[choice]) : text.valignChoices[choice],
              }))}
              onChange={(choice) => set({ valign: choice === defaultValign ? undefined : (choice as (typeof BAND_VALIGN)[number]) })}
            />
            <LabeledSelect
              label={`${title}: ${text.firstPageLabel.toLowerCase()}`} value={band.first_page ?? "same"} disabled={disabled} placeholder={null}
              help={strings.help.bandFirstPage}
              options={BAND_FIRST_PAGE.map((choice) => ({ value: choice, label: choice === "same" ? text.firstPageSame : text.firstPageNone }))}
              onChange={(choice) => set({ first_page: choice === "none" ? "none" : undefined })}
            />
          </div>
        </CollapsibleSection>
      )}
    </div>
  );
}
