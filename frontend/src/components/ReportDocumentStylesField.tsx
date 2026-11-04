/**
 * Module: components/ReportDocumentStylesField
 *
 * The **Fonts** setting of a document layout: the body font and size, and the headings' font, weight, slant and colour,
 * set once for the whole document (the layout tree's `styles` key).
 *
 * Responsibilities:
 * - Offer the fonts the server gives authors (the four standard ones, then those the server administrator provides) and
 *   the layout's colour scheme for the heading colour (the shared `ColourChoiceField`).
 * - Write the value in the tree's normal form: an unset part or setting is removed, never left empty, because the server
 *   refuses an empty object.
 * - Say when the chosen font is not one this server offers (it was removed or hidden): reports then print in a standard font.
 * - Show a rough sample in the browser's own typeface of the same kind (serif, sans-serif or monospace).
 *
 * Design decisions: the sample is approximate on purpose. The report's own font files are not on the page, so the sample
 * only shows the kind of face; the server remains the judge of what prints. Font and size are for the whole document: a
 * block's own font is a separate setting (`FontChoiceField` in the block's form).
 */
import type { ReportFontChoice } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import type { ColourContext, ColourEntry } from "../utils/reportColours";
import { STANDARD_FONT_CHOICES, type DocumentStyles } from "../utils/reportFonts";
import { ColourChoiceField } from "./ColourChoiceField";
import { FontChoiceField } from "./FontChoiceField";
import { CheckboxField, TextField } from "./FormFields";

/** Removes empty settings and parts, so what is stored is what the server accepts. */
function tidy(styles: DocumentStyles): DocumentStyles | undefined {
  const body = Object.fromEntries(Object.entries(styles.body ?? {}).filter(([, v]) => v !== undefined && v !== ""));
  const headings = Object.fromEntries(Object.entries(styles.headings ?? {}).filter(([, v]) => v !== undefined && v !== ""));
  const next: DocumentStyles = {
    ...(Object.keys(body).length > 0 ? { body } : {}),
    ...(Object.keys(headings).length > 0 ? { headings } : {}),
  };
  return Object.keys(next).length > 0 ? next : undefined;
}

/**
 * @param label The field's caption (the group's legend).
 * @param value The stored `styles` value.
 * @param onChange Called with the new value, `undefined` when nothing is set any more.
 * @param fonts The fonts an author may choose; the four standard ones when absent.
 * @param colours The branding colour and the organisation's scheme, for the heading colour.
 * @param palette The layout's own colour scheme.
 * @param disabled Read-only.
 */
export function ReportDocumentStylesField({
  label, value, onChange, fonts = STANDARD_FONT_CHOICES, colours, palette = [], disabled = false,
}: {
  label: string;
  value: DocumentStyles | undefined;
  onChange: (next: DocumentStyles | undefined) => void;
  fonts?: ReportFontChoice[];
  colours: ColourContext;
  palette?: ColourEntry[];
  disabled?: boolean;
}) {
  const text = useStrings().reportDocumentFonts;
  const help = useStrings().help;
  const styles = value ?? {};
  const body = styles.body ?? {};
  const headings = styles.headings ?? {};
  const setBody = (patch: Partial<NonNullable<DocumentStyles["body"]>>) => onChange(tidy({ ...styles, body: { ...body, ...patch } }));
  const setHeadings = (patch: Partial<NonNullable<DocumentStyles["headings"]>>) => onChange(tidy({ ...styles, headings: { ...headings, ...patch } }));
  const missing = [body.font, headings.font].filter((k): k is string => !!k && !fonts.some((f) => f.key === k));
  const genericOf = (key: string | undefined) => fonts.find((f) => f.key === (key ?? ""))?.generic ?? "sans-serif";
  const headingKey = headings.font ?? body.font;
  return (
    <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
      <legend><strong>{label}</strong></legend>
      <FontChoiceField
        label={text.bodyFont} value={body.font} disabled={disabled} help={help.reportBodyFont} fonts={fonts}
        emptyLabel={text.defaultFont} onChange={(font) => setBody({ font: font || undefined })}
      />
      <TextField
        label={text.bodySize} value={body.size === undefined ? "" : String(body.size)} disabled={disabled} help={help.reportBodySize}
        inputProps={{ type: "number", min: 6, max: 72, step: 0.5 }}
        onChange={(t) => setBody({ size: t.trim() === "" || Number.isNaN(Number(t)) ? undefined : Number(t) })}
      />
      <FontChoiceField
        label={text.headingFont} value={headings.font} disabled={disabled} help={help.reportHeadingFont} fonts={fonts}
        emptyLabel={text.sameAsBody} onChange={(font) => setHeadings({ font: font || undefined })}
      />
      <CheckboxField
        label={text.headingBold} checked={headings.bold !== false} disabled={disabled} help={help.reportHeadingBold}
        onChange={(on) => setHeadings({ bold: on ? undefined : false })}
      />
      <CheckboxField
        label={text.headingItalic} checked={headings.italic === true} disabled={disabled} help={help.reportHeadingItalic}
        onChange={(on) => setHeadings({ italic: on ? true : undefined })}
      />
      <ColourChoiceField
        label={text.headingColour} value={headings.colour ?? ""} disabled={disabled} help={help.reportHeadingColour}
        context={colours} layoutPalette={palette} allowNone={false} emptyLabel={text.defaultColour}
        onChange={(colour) => setHeadings({ colour: colour || undefined })}
      />
      {missing.map((key) => <p key={key} role="status" className="text-muted">{text.unavailableWarning(key)}</p>)}
      <div className="stack" style={{ gap: "var(--space-1)" }} aria-hidden="true">
        <span
          style={{
            fontFamily: headingKey === undefined ? undefined : genericOf(headingKey), fontWeight: headings.bold === false ? "normal" : "bold",
            fontStyle: headings.italic ? "italic" : "normal", fontSize: "1.1rem",
          }}
        >
          {text.sampleHeading}
        </span>
        <span style={{ fontFamily: body.font === undefined ? undefined : genericOf(body.font), fontSize: body.size ? `${body.size}pt` : undefined }}>
          {text.sampleBody}
        </span>
      </div>
      <p className="text-muted">{text.sampleNote}</p>
    </fieldset>
  );
}
