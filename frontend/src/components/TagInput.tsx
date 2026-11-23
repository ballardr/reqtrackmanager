/**
 * Module: components/TagInput
 *
 * The tag picker: the chosen tags as removable chips followed by a `[+]` chip. The `[+]` opens a
 * `Popover` holding one text box; typing filters the vocabulary and Enter, a click, a comma or a
 * semicolon adds the highlighted (or typed) tag.
 *
 * Responsibilities:
 * - Draw the chips and the `[+]` that opens the shared `TagAddBox` (the text box, the suggestions and the rules for
 *   a free and a restricted project) in the popover.
 * - Report each change through `onChange`; nothing is saved here.
 *
 * Design decisions: the text box lives in a popover, not in the row, so a form or a record header
 * shows chips and one small control rather than a full-width field. The chips keep their vocabulary colour.
 */
import { Plus } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { normaliseTagName, type TagChipData } from "../api/tags";
import { useStrings } from "../context/TerminologyContext";
import { Popover } from "./Popover";
import { TagAddBox } from "./TagAddBox";
import { TagChip } from "./TagChip";
import { Tooltip } from "./Tooltip";

const key = (name: string) => normaliseTagName(name).toLowerCase();

/**
 * @param value The chosen tag names.
 * @param onChange Called with the new list after an add or a removal.
 * @param suggestions The vocabulary to pick from (with colours).
 * @param restricted True when only listed tags may be applied.
 * @param label Accessible name of the text box.
 * @param disabled Show the chips without the box and remove controls.
 */
export function TagInput({
  value, onChange, suggestions, restricted = false, label, disabled = false,
}: {
  value: string[];
  onChange: (names: string[]) => void;
  suggestions: TagChipData[];
  restricted?: boolean;
  label?: string;
  disabled?: boolean;
}) {
  const strings = useStrings();
  const [popoverOpen, setPopoverOpen] = useState(false);
  const addRef = useRef<HTMLButtonElement>(null);
  const colourOf = useMemo(() => new Map(suggestions.map((t) => [key(t.name), t.colour])), [suggestions]);
  const addLabel = strings.tags.addTag;
  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <div className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
        {value.length === 0 && disabled && <span className="text-muted">{strings.tags.none}</span>}
        {value.map((name) => (
          <TagChip
            key={key(name)}
            tag={{ name, colour: colourOf.get(key(name)) ?? null }}
            removeLabel={strings.tags.removeLabel(name)}
            onRemove={disabled ? undefined : () => onChange(value.filter((n) => key(n) !== key(name)))}
          />
        ))}
        {!disabled && (
          <Tooltip label={addLabel}>
            <button
              ref={addRef}
              type="button"
              className="chip tag-add"
              aria-label={addLabel}
              aria-haspopup="dialog"
              aria-expanded={popoverOpen}
              onClick={() => setPopoverOpen((o) => !o)}
            >
              <Plus size={12} aria-hidden="true" />
            </button>
          </Tooltip>
        )}
      </div>
      {popoverOpen && !disabled && (
        <Popover anchorRef={addRef} title={addLabel} onClose={() => setPopoverOpen(false)} fit>
          <TagAddBox
            value={value} onChange={onChange} suggestions={suggestions} restricted={restricted} label={label}
            onDone={() => setPopoverOpen(false)}
          />
        </Popover>
      )}
    </div>
  );
}
