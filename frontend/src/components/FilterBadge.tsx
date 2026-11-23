import type { CSSProperties, ReactNode } from "react";

import type { BadgeTone } from "../api/types";
import { badgeClassName } from "./badgeClassName";

/**
 * A `.badge` that also acts as a filter shortcut: clicking it applies (or, if applied, clears) the filter it
 * represents, as picking it in the filter panel's dropdown does. `active` adds a visual affordance only.
 *
 * `tone` applies the status-colour `.badge--<tone>` modifier from the relevant `*_TONE` map (api/types.ts) for a
 * status or outcome enum; omit it for a neutral badge.
 *
 * `pressed` exposes the on/off state to assistive technology (`aria-pressed`) for a stand-alone toggle
 * (`ToggleChips`) rather than a shortcut into a filter shown elsewhere.
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
