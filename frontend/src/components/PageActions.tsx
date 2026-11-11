/**
 * Module: components/PageActions
 *
 * Lets a section rendered inside a page put its own actions (an Export trigger, for example) in the page's title row,
 * beside the page's other actions, while the section keeps the state those actions need (its filters, its data).
 *
 * - `PageActionsProvider` wraps the page and holds the mount point.
 * - `PageActionsSlot` is the mount point, placed in the title row's action group.
 * - `PageActions` wraps the section's actions: it renders them into the slot when the page has one, and inline
 *   (right-aligned) when it has none, so a section used on its own still shows them.
 *
 * Design: a portal keeps the actions in one fixed place whichever section is shown (switching sections does not move
 * the controls), and keeps a core page from naming any module; a module section only declares its actions
 * (docs/ux-style-guide.md, "Pattern: page actions").
 */
import { createContext, useContext, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

const SlotContext = createContext<{ node: HTMLElement | null; setNode: (node: HTMLElement | null) => void } | null>(null);

/**
 * @param children The page, which renders a `PageActionsSlot` in its title row.
 */
export function PageActionsProvider({ children }: { children: ReactNode }) {
  const [node, setNode] = useState<HTMLElement | null>(null);
  return <SlotContext.Provider value={{ node, setNode }}>{children}</SlotContext.Provider>;
}

/** The title row's mount point for the actions a section contributes; renders nothing visible while it has none. */
export function PageActionsSlot() {
  const slot = useContext(SlotContext);
  return <div ref={slot?.setNode} className="row" style={{ alignItems: "center", gap: "var(--space-1)" }} />;
}

/**
 * @param children The section's actions, shown in the page's title row (or inline when the page has no slot).
 */
export function PageActions({ children }: { children: ReactNode }) {
  const slot = useContext(SlotContext);
  if (!slot) return <div className="row" style={{ justifyContent: "flex-end" }}>{children}</div>;
  // The slot's element exists after the page's first render; until then nothing is shown.
  return slot.node ? createPortal(children, slot.node) : null;
}
