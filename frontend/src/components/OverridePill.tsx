import { t } from "../i18n/strings";
import { Badge } from "./Badge";

const strings = t();

/**
 * Style guide "Pattern: platform default vs. override" (docs/ux-style-guide.md): one control for every setting that
 * falls back to a platform-wide default when unset. It states the current source in words (`custom` reflects the
 * last saved value, not an in-progress edit, so it matches what a reload shows) and offers an explicit way back
 * instead of expecting the field to be emptied.
 *
 * `onReset` clears the field locally; the caller's own save action persists the revert, as every field in these
 * forms batches edits behind one Save button.
 *
 * `platformFallback` is for an organisation-page setting whose fallback is the platform or module default:
 * organisations do not manage that default, so no pill says "Custom" or "Platform default"; only a reset button
 * stays, shown while the value differs (a value that cannot be emptied, such as a band set, has no other way back).
 * A pill naming an inherited tier (organisation, parent project) is not this case and stays.
 *
 * `defaultLabel`/`resetLabel` replace "Platform default"/"Reset to platform default" where the fallback is not the
 * platform, e.g. a project setting inherited from its parent project or organisation ("Inherited from
 * organisation" / "Use inherited value").
 */
export function OverridePill({
  custom, onReset, disabled, defaultLabel, resetLabel, platformFallback,
}: { custom: boolean; onReset?: () => void; disabled?: boolean; defaultLabel?: string; resetLabel?: string; platformFallback?: boolean }) {
  if (platformFallback) {
    if (!custom || !onReset) return null;
    return (
      <button type="button" className="btn" onClick={onReset} disabled={disabled}>
        {resetLabel ?? strings.common.resetToPlatformDefault}
      </button>
    );
  }
  if (!custom) {
    return <Badge>{defaultLabel ?? strings.common.platformDefault}</Badge>;
  }
  return (
    <span className="row" style={{ gap: "var(--space-3)", display: "inline-flex" }}>
      <Badge>{strings.common.customValue}</Badge>
      {onReset && (
        <button type="button" className="btn" onClick={onReset} disabled={disabled}>
          {resetLabel ?? strings.common.resetToPlatformDefault}
        </button>
      )}
    </span>
  );
}
