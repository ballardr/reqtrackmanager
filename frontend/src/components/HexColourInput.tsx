/**
 * Module: components/HexColourInput
 *
 * The browser's colour picker and a hex box kept in sync: the pair `ColorField` and `ColourChoiceField` share, so a
 * custom colour is typed and chosen the same way everywhere.
 *
 * Design decisions: only plain hex is ever reported (`#rrggbb`, lower case). Text that is not a colour stays in the box
 * while it is typed, is flagged, and is never reported.
 */
import { useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { normaliseHexColour } from "../utils/color";

/**
 * @param value The current `#rrggbb`, or anything else for none (the picker then shows black).
 * @param onChange Called with a valid `#rrggbb`.
 * @param name Accessible name of the picker; the hex box says "<name> (hex code)".
 * @param id The picker's id, so a caption can point at it.
 */
export function HexColourInput({
  value, onChange, name, id,
}: { value: string; onChange: (hex: string) => void; name: string; id?: string }) {
  const strings = useStrings();
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? value;
  const invalid = draft !== null && draft.trim() !== "" && normaliseHexColour(draft) === null;
  return (
    <>
      <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
        <input
          id={id} type="color" value={normaliseHexColour(value) ?? "#000000"} aria-label={name}
          onChange={(e) => { setDraft(null); onChange(e.target.value); }}
          style={{ width: 60, height: 36, padding: 2 }}
        />
        <input
          className="input" style={{ width: "7rem" }} value={shown} maxLength={7} spellCheck={false}
          aria-label={strings.common.hexCode(name)} aria-invalid={invalid || undefined} placeholder="#rrggbb"
          onChange={(e) => {
            setDraft(e.target.value);
            const hex = normaliseHexColour(e.target.value);
            if (hex) onChange(hex);
          }}
          onBlur={() => setDraft(null)}
        />
      </span>
      {invalid && <span role="alert" style={{ fontSize: "0.8rem", color: "var(--color-danger)" }}>{strings.common.hexCodeInvalid}</span>}
    </>
  );
}
