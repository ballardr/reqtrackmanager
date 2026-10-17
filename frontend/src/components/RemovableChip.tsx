import { Trash2 } from "lucide-react";

/**
 * A removable chip: a file name or small value with a remove control inside it (a pending upload, an
 * attachment on a comment being edited). Not a pill: pills (`Badge`) are read-only status labels; a chip
 * holds a control, so its text wraps and the remove button stays beside it (`flex: none`).
 *
 * @param label The text shown (wraps when long).
 * @param removeLabel Accessible name and tooltip of the remove button.
 * @param onRemove Called when the remove button is pressed; omit to show the chip without a control.
 */
export function RemovableChip({
  label, removeLabel, onRemove,
}: { label: string; removeLabel: string; onRemove?: () => void }) {
  return (
    <span className="chip">
      <span className="chip__label">{label}</span>
      {onRemove && (
        <button type="button" className="chip__remove" title={removeLabel} aria-label={removeLabel} onClick={onRemove}>
          <Trash2 size={12} />
        </button>
      )}
    </span>
  );
}
