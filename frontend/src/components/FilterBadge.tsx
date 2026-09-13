import type { CSSProperties, ReactNode } from "react";

import type { BadgeTone } from "../api/types";

/**
 * A `.badge` that also acts as a filter shortcut: clicking it applies (or,
 * if already applied, clears) the filter it represents — e.g. clicking a
 * requirement's status badge filters the list to that status, same as
 * picking it from the filter panel's own dropdown. `active` just adds a
 * visual affordance (no different from a plain badge otherwise), so
 * whether the underlying filter is already set to this value stays
 * obvious even before hovering.
 *
 * `tone` (platform review 2026-09, Phase 4) applies the status-colour
 * `.badge--<tone>` modifier — pass the value from the relevant `*_TONE`
 * map (api/types.ts) when this badge represents a status/outcome enum;
 * omit it for badges that don't (e.g. a target-stage filter), which keeps
 * today's plain neutral look.
 */
export function FilterBadge({
  active = false,
  onClick,
  children,
  title,
  style,
  tone,
}: {
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
  title?: string;
  style?: CSSProperties;
  tone?: BadgeTone;
}) {
  return (
    <button
      type="button"
      className={tone ? `badge badge--${tone}` : "badge"}
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
