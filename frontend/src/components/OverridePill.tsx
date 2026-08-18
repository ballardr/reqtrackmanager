import { t } from "../i18n/strings";

const strings = t();

/**
 * Style guide "Pattern: platform default vs. override" (docs/ux-style-guide.md):
 * one control, applied uniformly to every setting that falls back to a
 * platform-wide default when unset. States the current source in words —
 * `custom` reflects the last-*saved* value, not an in-progress edit, so it
 * stays honest about what a reload would actually show — and offers an
 * explicit way back rather than expecting the field to be blanked by hand.
 *
 * `onReset` clears the field locally; it's the caller's own save action
 * (not this component) that persists the revert, matching how every other
 * field in these forms already batches edits behind one Save button rather
 * than saving per-field.
 */
export function OverridePill({
  custom, onReset, disabled,
}: { custom: boolean; onReset?: () => void; disabled?: boolean }) {
  if (!custom) {
    return <span className="badge">{strings.common.platformDefault}</span>;
  }
  return (
    <span className="row" style={{ gap: "0.5rem", display: "inline-flex" }}>
      <span className="badge">{strings.common.customValue}</span>
      {onReset && (
        <button type="button" className="btn" onClick={onReset} disabled={disabled}>
          {strings.common.resetToPlatformDefault}
        </button>
      )}
    </span>
  );
}
