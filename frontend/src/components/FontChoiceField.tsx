/**
 * Module: components/FontChoiceField
 *
 * The font select shared by every report setting that names a font (the layout's body and heading fonts, a text
 * or heading block's own font): a thin wrapper over `LabeledSelect` listing the fonts the server gives authors
 * (the four standard ones, then those the server administrator provides, marked) behind a leading empty option
 * saying what an empty value inherits. A stored font the server does not offer stays selectable and labelled, so
 * it is shown rather than dropped. The server decides what is valid.
 */
import type { FieldHelpProps } from "./FieldHelp";
import { useStrings } from "../context/TerminologyContext";
import type { ReportFontChoice } from "../api/reportLayouts";
import { STANDARD_FONT_CHOICES } from "../utils/reportFonts";
import { LabeledSelect } from "./LabeledSelect";

/**
 * @param label The field's caption.
 * @param value The stored font key, `""` or `undefined` for none.
 * @param onChange Called with the chosen key, `""` for the empty option.
 * @param emptyLabel What an empty value means ("Document font"); shown as the empty option.
 * @param fonts The fonts an author may choose; the four standard ones when absent.
 * @param disabled Read-only.
 */
export function FontChoiceField({
  label, value, onChange, emptyLabel, fonts = STANDARD_FONT_CHOICES, disabled = false, help,
}: Pick<FieldHelpProps, "help"> & {
  label: string;
  value: string | undefined;
  onChange: (key: string) => void;
  emptyLabel: string;
  fonts?: ReportFontChoice[];
  disabled?: boolean;
}) {
  const text = useStrings().reportDocumentFonts;
  const known = !value || fonts.some((f) => f.key === value);
  const options = [
    ...fonts.filter((f) => f.bundled).map((f) => ({ value: f.key, label: f.label })),
    ...fonts.filter((f) => !f.bundled).map((f) => ({ value: f.key, label: `${f.label} (${text.extraGroup.toLowerCase()})` })),
    ...(known ? [] : [{ value: value as string, label: text.unavailable(value as string) }]),
  ];
  return (
    <LabeledSelect
      label={label} value={value ?? ""} disabled={disabled} placeholder={emptyLabel} options={options} onChange={onChange}
      help={help}
    />
  );
}
