/**
 * Module: components/StorageLimitField
 *
 * A labelled storage amount entered as a number and a unit (MB or GB), for a limit that is stored in bytes.
 *
 * Responsibilities: show the caption with its `(?)` help, one number input and one unit select side by side, and report
 * the typed text and the unit separately; converting to and from bytes is `utils/storageLimit`.
 * Design decisions: an empty amount is meaningful (no limit, or "follow the default"), so the caller supplies the
 * placeholder that says which. External dependencies: `FieldShell`, `InlineSelect`.
 */
import { useId } from "react";

import { useStrings } from "../context/TerminologyContext";
import type { StorageUnit } from "../utils/storageLimit";

import { FieldShell } from "./FieldHelp";
import { InlineSelect } from "./LabeledSelect";

/**
 * @param label The caption.
 * @param help The help text for the `(?)` button.
 * @param amount The typed amount (empty for none).
 * @param unit The chosen unit.
 * @param onAmountChange Called with the typed text.
 * @param onUnitChange Called with the chosen unit.
 * @param placeholder Text shown when the amount is empty (what an empty amount means).
 * @param disabled Whether the field is read-only.
 */
export function StorageLimitField({
  label, amount, unit, onAmountChange, onUnitChange, placeholder, disabled, help,
}: {
  label: string;
  /** The field's help text (`strings.help`). */
  help: string;
  amount: string;
  unit: StorageUnit;
  onAmountChange: (amount: string) => void;
  onUnitChange: (unit: StorageUnit) => void;
  placeholder: string;
  disabled?: boolean;
}) {
  const strings = useStrings();
  const id = useId();
  return (
    <FieldShell label={label} controlId={id} help={help}>
      <span className="row" style={{ gap: "var(--space-2)" }}>
        <input
          id={id} className="input" type="number" min={0} step="any" value={amount} disabled={disabled}
          placeholder={placeholder} aria-label={label} onChange={(e) => onAmountChange(e.target.value)} style={{ maxWidth: "14rem" }}
        />
        <InlineSelect<StorageUnit>
          ariaLabel={strings.orgStorage.limitUnit} value={unit} onChange={onUnitChange} disabled={disabled} placeholder={null}
          autoWidth options={[{ value: "MB", label: strings.orgStorage.unitMb }, { value: "GB", label: strings.orgStorage.unitGb }]}
        />
      </span>
    </FieldShell>
  );
}
