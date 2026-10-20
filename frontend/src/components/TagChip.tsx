/**
 * Module: components/TagChip
 *
 * One tag as shown on a record, in a list filter or in the tag admin: a chip whose left edge
 * carries the tag's own colour (user data, passed as `--tag-colour`), so the label stays in the
 * theme's text colour and is readable in light and dark. With `onRemove` it holds a remove
 * control, like any `RemovableChip`; without it it is read-only.
 */
import { X } from "lucide-react";
import type { CSSProperties } from "react";

import type { TagChipData } from "../api/tags";
import { normaliseHexColour } from "../utils/color";

/**
 * @param tag The tag (name and optional `#rrggbb` colour). The colour goes into a style attribute, so
 *   a stored value that is not plain hex is ignored and the chip shows no colour.
 * @param removeLabel Accessible name of the remove button (required when `onRemove` is given).
 * @param onRemove Called when the remove button is pressed; omit for a read-only chip.
 */
export function TagChip({
  tag, removeLabel, onRemove,
}: { tag: Pick<TagChipData, "name" | "colour">; removeLabel?: string; onRemove?: () => void }) {
  const colour = tag.colour ? normaliseHexColour(tag.colour) : null;
  return (
    <span className="chip tag-chip" style={colour ? ({ "--tag-colour": colour } as CSSProperties) : undefined}>
      <span className="chip__label">{tag.name}</span>
      {onRemove && (
        <button type="button" className="chip__remove" title={removeLabel} aria-label={removeLabel} onClick={onRemove}>
          <X size={12} />
        </button>
      )}
    </span>
  );
}
