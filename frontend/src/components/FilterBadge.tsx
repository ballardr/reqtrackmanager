import type { CSSProperties, ReactNode } from "react";

import type { BadgeTone } from "../api/types";
import { badgeClassName } from "./badgeClassName";

/**
 * A `.badge` that also acts as a filter shortcut: clicking it applies (or,
 * if already applied, clears) the filter it represents — e.g. clicking a
 * requirement's status badge filters the list to that status, same as
 * picking it from the filter panel's own dropdown. `active` just adds a
 * visual affordance (no different from a plain badge otherwise), so
 * whether the underlying filter is already set to this value stays
 * obvious even before hovering.
 *
 * `tone` applies the status-colour
 * `.badge--<tone>` modifier — pass the value from the relevant `*_TONE`
 * map (api/types.ts) when this badge represents a status/outcome enum;
 * omit it for badges that don't (e.g. a target-stage filter), which keeps
 * today's plain neutral look.
 *
 * `pressed` additionally exposes the on/off state to assistive tech (`aria-pressed`) for a badge that is
 * a stand-alone toggle (`ToggleChips`) rather than a shortcut into a filter shown elsewhere.
 */
export function FilterBadge({
  active = false,
  onClick,
  children,
  title,
  style,
  tone,
  pressed,
}: {
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
  title?: string;
  style?: CSSProperties;
  tone?: BadgeTone;
  pressed?: boolean;
}) {
  return (
    <button
      type="button"
      className={badgeClassName(tone)}
      onClick={onClick}
      aria-pressed={pressed}
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
