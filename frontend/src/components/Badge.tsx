import { Children, type CSSProperties, type HTMLAttributes, type ReactNode } from "react";

import type { BadgeTone } from "../api/types";
import { badgeClassName } from "./badgeClassName";
import { Tooltip } from "./Tooltip";

/** Longer plain-text labels than this can reach the two-line limit, so they get the full text as a Tooltip. */
const TOOLTIP_FROM_LENGTH = 36;

/** True when the label is only text and numbers (the case the two-line clamp applies to). */
function isPlainText(children: ReactNode): boolean {
  return Children.toArray(children).every((child) => typeof child === "string" || typeof child === "number");
}

/**
 * The one pill (style guide "Pattern: pills"): a status, type, role, scope or warning chip.
 *
 * One height, padding and font everywhere; the text is centred; the pill never shrinks and never
 * stretches to fill its row. It stays on one line up to a maximum width (about 22 characters) and then
 * wraps, centred, to at most two lines; past that the text is clipped with an ellipsis and, for a plain
 * string, the full text is offered as a Tooltip. Widths differ with content on purpose. To make every
 * pill in a list one width (a status column), put `badge-column` on the container or pass `minWidth`.
 * A label that holds an element (an icon, a name component) is laid out in a row and is not clamped.
 *
 * Render enum values through their `*_LABEL` map and pass the `*_TONE` map's value as `tone`
 * (Principle 12); never a raw backend string or an inline colour.
 *
 * @param tone Status colour from a `*_TONE` map; omit for neutral.
 * @param align Where the text sits when the pill is wider than it (a shared minimum width). Default centre.
 * @param minWidth CSS width every pill of this use should share (for example `"8rem"`).
 * @param icon Optional leading icon (sized to 12px by the caller).
 * @param children The label.
 */
export function Badge({
  tone, align = "center", minWidth, icon, className, style, children, ...rest
}: {
  tone?: BadgeTone;
  align?: "start" | "center" | "end";
  minWidth?: string;
  icon?: ReactNode;
  children: ReactNode;
} & Omit<HTMLAttributes<HTMLSpanElement>, "children">) {
  const rich = icon !== undefined || !isPlainText(children);
  const pill = (
    <span
      {...rest}
      className={badgeClassName(tone, [rich ? "badge--rich" : "", className ?? ""].filter(Boolean).join(" "))}
      data-align={align === "center" ? undefined : align}
      style={minWidth ? ({ "--badge-min-width": minWidth, ...style } as CSSProperties) : style}
    >
      {icon}
      {children}
    </span>
  );
  if (typeof children === "string" && children.length > TOOLTIP_FROM_LENGTH && !rest.title) {
    return <Tooltip label={children}>{pill}</Tooltip>;
  }
  return pill;
}
