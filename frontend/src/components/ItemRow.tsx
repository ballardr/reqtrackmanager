import type { ElementType, HTMLAttributes, ReactNode } from "react";

/**
 * Text beside controls (style guide "Pattern: text beside controls"): the content wraps inside its own box and the
 * actions stay beside it, however long the text is. Use it for every row, card header or list item with a title or
 * label plus Edit/Remove/Delete controls; `.row` stays the primitive for toolbars and filter bars, which wrap.
 *
 * The geometry check (`testing/orphanedControls`) fails when a control is alone at the start of a new line; this
 * component makes that structurally impossible.
 *
 * @param children The text or content that may be long.
 * @param actions Buttons and menus; `flex: none`, kept to the right.
 * @param as Element to render (`li`, `div`, ...). Default `div`.
 * @param align Cross-axis alignment: `center` (default) or `start` for multi-line content.
 * @param revealActions Show the actions only while the row is hovered or has keyboard focus inside it (style guide
 *   "Pattern: actions revealed on hover"). The actions keep their space, so the row never changes size, and a device
 *   with no hover always shows them.
 */
export function ItemRow({
  children, actions, as, align = "center", revealActions = false, className, style, ...rest
}: {
  children: ReactNode;
  actions?: ReactNode;
  as?: ElementType;
  align?: "center" | "start";
  revealActions?: boolean;
} & Omit<HTMLAttributes<HTMLElement>, "children">) {
  const Tag = as ?? "div";
  return (
    <Tag
      {...rest}
      className={["item-row", revealActions && "item-row--reveal", className].filter(Boolean).join(" ")}
      style={align === "start" ? { alignItems: "flex-start", ...style } : style}
    >
      <div className="item-row__content">{children}</div>
      {actions && <div className="item-row__actions">{actions}</div>}
    </Tag>
  );
}
