/**
 * Module: components/PageStylesEditor
 *
 * The list of a document layout's named page styles (paper, orientation and margins) that its sections lay their
 * contents out in. One editor serves the text view's page setup dialog and the Blocks view's layout settings.
 *
 * Responsibilities: add a style, rename it, choose its paper and orientation (or leave them on the layout's own),
 * set its margins (an emptied side shares the layout's), sketch the page, and remove it. The editor edits the list it
 * is given and never judges it: the server checks names, ranges and that the margins leave room for text.
 */
import { Trash2 } from "lucide-react";

import { useStrings } from "../context/TerminologyContext";
import {
  MAX_PAGE_STYLES, PAGE_ORIENTATIONS, PAGE_SIZES, type PageMargins, type PageOrientation, type PageSize, type PageStyleSetup,
} from "../utils/reportPageSetup";
import { TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { PageMarginsFields } from "./PageMarginsFields";
import { PageOutline } from "./PageOutline";
import { Tooltip } from "./Tooltip";

/** What a style shares when it leaves a value out: the layout's own page. */
export interface PageStyleBase {
  size: PageSize;
  orientation: PageOrientation;
  margins: PageMargins;
  mirror: boolean;
}

/**
 * @param value The styles, in the order they are listed.
 * @param onChange Called with the styles after any edit.
 * @param base The layout's own page, which a style inherits what it leaves out from.
 * @param disabled Whether the editor is read-only.
 */
export function PageStylesEditor({
  value, onChange, base, disabled = false,
}: { value: PageStyleSetup[]; onChange: (next: PageStyleSetup[]) => void; base: PageStyleBase; disabled?: boolean }) {
  const strings = useStrings();
  const text = strings.pageSetup;
  const change = (index: number, patch: Partial<PageStyleSetup>) => {
    const next = value.map((style, i) => (i === index ? { ...style, ...patch } : style));
    // A value set back to "same as the layout" is removed from the style, not kept as undefined.
    onChange(next.map((style) => {
      const clean = { ...style };
      for (const key of ["size", "orientation", "margins"] as const) if (clean[key] === undefined) delete clean[key];
      return clean;
    }));
  };
  const add = () => {
    const taken = new Set(value.map((style) => style.name));
    let n = value.length + 1;
    while (taken.has(text.newStyleName(n))) n += 1;
    onChange([...value, { name: text.newStyleName(n) }]);
  };
  return (
    <div className="stack">
      <p style={{ margin: 0, color: "var(--color-text-muted)" }}>{text.stylesIntro}</p>
      {value.length === 0 && <p style={{ margin: 0 }}>{text.noStyles}</p>}
      {value.map((style, index) => {
        const size = style.size ?? base.size;
        const orientation = style.orientation ?? base.orientation;
        return (
          <div key={index} role="group" aria-label={style.name || text.styleName} className="card stack">
            <div className="row" style={{ alignItems: "flex-end", gap: "var(--space-3)" }}>
              <PageOutline size={size} orientation={orientation} margins={{ ...base.margins, ...style.margins }} mirror={base.mirror} />
              <div style={{ flex: 1, minWidth: "10rem" }}>
                <TextField
                  label={text.styleName} value={style.name} onChange={(name) => change(index, { name })} disabled={disabled}
                  help={strings.help.pageStyleName} required inputProps={{ maxLength: 40 }}
                />
              </div>
              <LabeledSelect
                label={text.sizeLabel} value={style.size ?? ""} disabled={disabled} help={strings.help.pageStyleSize}
                placeholder={text.sameAsLayout(base.size)}
                options={PAGE_SIZES.map((s) => ({ value: s, label: s }))}
                onChange={(next) => change(index, { size: (next || undefined) as PageSize | undefined })}
              />
              <LabeledSelect
                label={text.orientationLabel} value={style.orientation ?? ""} disabled={disabled} help={strings.help.pageStyleOrientation}
                placeholder={text.sameAsLayout(text.orientationLabels[base.orientation])}
                options={PAGE_ORIENTATIONS.map((o) => ({ value: o, label: text.orientationLabels[o] }))}
                onChange={(next) => change(index, { orientation: (next || undefined) as PageOrientation | undefined })}
              />
              {!disabled && (
                <Tooltip label={text.removeStyle(style.name)}>
                  <button
                    type="button" className="btn btn-sm btn-icon" aria-label={text.removeStyle(style.name)}
                    onClick={() => onChange(value.filter((_, i) => i !== index))}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                </Tooltip>
              )}
            </div>
            <PageMarginsFields
              value={style.margins ?? {}} inherited={base.margins} mirror={base.mirror} disabled={disabled} styleField
              onChange={(margins) => change(index, { margins: Object.keys(margins).length === 0 ? undefined : margins })}
            />
          </div>
        );
      })}
      {!disabled && value.length < MAX_PAGE_STYLES && (
        <div><button type="button" className="btn btn-sm" onClick={add}>{text.addStyle}</button></div>
      )}
    </div>
  );
}
