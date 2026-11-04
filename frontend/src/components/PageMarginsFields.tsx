/**
 * Module: components/PageMarginsFields
 *
 * The five margin fields of a page setup (top, bottom, left, right and the gutter, in cm), shared by the page
 * setup dialog, the layout settings and each page style so a margin looks and behaves the same everywhere.
 *
 * Responsibilities: show one number field per side, write a side back (an emptied side is removed, so it falls back
 * to the layout's own), show the inherited value as the placeholder, and name left and right as the inner and outer
 * edge while margins mirror. The server checks the range; the inputs only carry its bounds.
 */
import { useStrings } from "../context/TerminologyContext";
import {
  MARGIN_SIDES, MAX_GUTTER_CM, MAX_MARGIN_CM, MIN_MARGIN_CM, effectiveMargins, type MarginSide, type PageMargins,
} from "../utils/reportPageSetup";
import { TextField } from "./FormFields";

/** Help text per side that needs it; top and bottom explain themselves. */
const HELP: Partial<Record<MarginSide, "layoutMarginLeft" | "layoutMarginRight" | "layoutMarginGutter" | "pageStyleMargin">> = {
  left: "layoutMarginLeft", right: "layoutMarginRight", gutter: "layoutMarginGutter",
};

/**
 * @param value The margins set so far.
 * @param onChange Called with the margins after a side changes.
 * @param inherited What a side that is left empty takes (a page style's layout), shown as the placeholder.
 * @param mirror Whether margins mirror, which makes left and right the inner and outer edge.
 * @param disabled Whether the fields are read-only.
 * @param styleField True inside a page style, where every side shares one help text about inheriting.
 */
export function PageMarginsFields({
  value, onChange, inherited, mirror = false, disabled = false, styleField = false,
}: {
  value: PageMargins;
  onChange: (next: PageMargins) => void;
  inherited?: PageMargins;
  mirror?: boolean;
  disabled?: boolean;
  styleField?: boolean;
}) {
  const strings = useStrings();
  const text = strings.pageSetup;
  const shown = effectiveMargins(undefined, inherited);
  const set = (side: MarginSide, input: string) => {
    const next = { ...value };
    const number = Number(input);
    if (input.trim() === "" || Number.isNaN(number)) delete next[side];
    else next[side] = number;
    onChange(next);
  };
  const label = (side: MarginSide) => (mirror && side === "left" ? text.innerLabel : mirror && side === "right" ? text.outerLabel : text.sideLabels[side]);
  return (
    <div className="row" style={{ gap: "var(--space-3)", alignItems: "flex-end" }}>
      {MARGIN_SIDES.map((side) => {
        const key = styleField ? "pageStyleMargin" : HELP[side];
        const high = side === "gutter" ? MAX_GUTTER_CM : MAX_MARGIN_CM;
        return (
          <div key={side} style={{ width: "6.5rem" }}>
            <TextField
              label={label(side)} value={value[side] === undefined ? "" : String(value[side])} disabled={disabled}
              placeholder={String(shown[side])}
              {...(key ? { help: strings.help[key] } : { helpNotNeeded: true })}
              inputProps={{ type: "number", min: side === "gutter" ? 0 : MIN_MARGIN_CM, max: high, step: 0.1 }}
              onChange={(input) => set(side, input)}
            />
          </div>
        );
      })}
    </div>
  );
}
