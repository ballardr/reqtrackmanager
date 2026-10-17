import type { ElementType, HTMLAttributes, ReactNode } from "react";

/**
 * Text beside controls (style guide "Pattern: text beside controls"): the content wraps inside its own
 * box and the actions stay beside it (never under it), however long the text is. Use it
 * for every row, card header or list item that has a title or label plus Edit/Remove/Delete controls.
 * `.row` stays the right primitive for toolbars and filter bars, which are meant to wrap.
 *
 * The geometry check (`testing/orphanedControls`) fails when a control ends up alone at the start of a
 * new line; this component is what makes that structurally impossible rather than a matter of care.
 *
 * @param children The text or content that may be long.
 * @param actions Buttons and menus; `flex: none`, kept to the right.
 * @param as Element to render (`li`, `div`, ...). Default `div`.
 * @param align Cross-axis alignment: `center` (default) or `start` for multi-line content.
 */
export function ItemRow({
  children, actions, as, align = "center", className, style, ...rest
}: {
  children: ReactNode;
  actions?: ReactNode;
  as?: ElementType;
  align?: "center" | "start";
} & Omit<HTMLAttributes<HTMLElement>, "children">) {
  const Tag = as ?? "div";
  return (
    <Tag
      {...rest}
      className={["item-row", className].filter(Boolean).join(" ")}
      style={align === "start" ? { alignItems: "flex-start", ...style } : style}
    >
      <div className="item-row__content">{children}</div>
      {actions && <div className="item-row__actions">{actions}</div>}
    </Tag>
  );
}
