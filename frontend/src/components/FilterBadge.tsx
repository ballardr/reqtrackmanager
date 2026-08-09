import type { CSSProperties, ReactNode } from "react";

/**
 * A `.badge` that also acts as a filter shortcut: clicking it applies (or,
 * if already applied, clears) the filter it represents — e.g. clicking a
 * requirement's status badge filters the list to that status, same as
 * picking it from the filter panel's own dropdown. `active` just adds a
 * visual affordance (no different from a plain badge otherwise), so
 * whether the underlying filter is already set to this value stays
 * obvious even before hovering.
 */
export function FilterBadge({
  active = false,
  onClick,
  children,
  title,
  style,
}: {
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
  title?: string;
  style?: CSSProperties;
}) {
  return (
    <button
      type="button"
      className="badge"
      onClick={onClick}
      title={title}
      style={{
        cursor: "pointer",
        borderColor: active ? "var(--color-primary)" : undefined,
        boxShadow: active ? "inset 0 0 0 1px var(--color-primary)" : undefined,
        ...style,
      }}
    >
      {children}
    </button>
  );
}
