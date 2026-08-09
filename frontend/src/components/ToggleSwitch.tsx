/**
 * A binary on/off switch styled as a pill, for settings that are a single
 * yes/no state rather than a momentary action — distinct from `.btn`,
 * which reads as "do this now" rather than "this is on/off". Exposed as
 * `role="switch"` for assistive tech rather than a native `<input
 * type="checkbox">`, since the pill visual has no direct HTML equivalent.
 */
export function ToggleSwitch({
  checked,
  onChange,
  disabled = false,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      style={{
        width: 40,
        height: 22,
        borderRadius: 999,
        border: "1px solid var(--color-border)",
        background: checked ? "var(--color-primary)" : "var(--color-surface-alt)",
        position: "relative",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.55 : 1,
        padding: 0,
        flexShrink: 0,
        transition: "background 0.15s ease",
      }}
    >
      <span
        style={{
          position: "absolute",
          top: 2,
          left: checked ? 20 : 2,
          width: 16,
          height: 16,
          borderRadius: "50%",
          background: checked ? "var(--color-primary-contrast)" : "var(--color-text-muted)",
          transition: "left 0.15s ease",
        }}
      />
    </button>
  );
}
