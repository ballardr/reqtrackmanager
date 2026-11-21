/**
 * Module: components/ActiveFieldFrame
 *
 * The frame of a rich text field (the Markdown editor's Visual and Write views, the policy editor) that shows the
 * field's formatting toolbar only while the person is working in it.
 *
 * Responsibilities:
 * - Track whether focus is anywhere inside the frame (the editor, the toolbar buttons, the link entry, the Write,
 *   Preview and Visual switch) and tell `ActiveFieldToolbar` through context.
 * - Draw a toolbar slot that keeps its place while hidden, so the field never moves when focus enters or leaves, and
 *   takes its buttons out of the tab order and the accessibility tree while hidden.
 * - Keep focus in the editor when a toolbar button is pressed, so pressing a button does not hide the toolbar (some
 *   browsers do not focus a button on click, which would end the focus inside the frame) and the selection survives.
 *
 * Design decisions:
 * - Focus within the frame decides, not the pointer (a touch screen has no hover) and not the editor alone (pressing
 *   a button moves focus to the button, which would hide the toolbar mid-action).
 * - The toolbar is rendered while hidden, not removed, so the space is reserved and the toolbar state (a link being
 *   entered) is kept; `visibility: hidden` is what removes it from the tab order and the accessibility tree.
 * - A frame inside another frame tracks nothing, so the field's own frame decides for the editor nested in it.
 * - There is no setting to keep the toolbar always visible: one rule for every rich text field.
 */
import { createContext, useContext, useState, type CSSProperties, type FocusEvent, type MouseEvent, type ReactNode } from "react";

/** Whether focus is inside the nearest frame; null outside any frame. */
const ActiveFieldContext = createContext<boolean | null>(null);

/**
 * @param children The field: its editor, its view switch and its `ActiveFieldToolbar`.
 * @param className The frame's class (the field's own layout).
 * @param style The frame's inline style.
 * @returns The field wrapped so that focus inside it is tracked.
 */
export function ActiveFieldFrame({ children, className, style }: { children: ReactNode; className?: string; style?: CSSProperties }) {
  const outer = useContext(ActiveFieldContext);
  const [active, setActive] = useState(false);
  // Nested in a field's frame: that frame decides, so this one only supplies the layout.
  if (outer !== null) return <div className={className} style={style}>{children}</div>;

  function leave(event: FocusEvent<HTMLDivElement>) {
    // Focus moving to another control inside the frame is not leaving it.
    if (!event.currentTarget.contains(event.relatedTarget)) setActive(false);
  }

  return (
    <ActiveFieldContext.Provider value={active}>
      <div className={className} style={style} onFocus={() => setActive(true)} onBlur={leave}>
        {children}
      </div>
    </ActiveFieldContext.Provider>
  );
}

/**
 * The slot a toolbar is drawn in: visible while focus is inside the enclosing `ActiveFieldFrame`, hidden (but still
 * occupying its space) otherwise. Outside any frame the toolbar is always visible.
 *
 * @param children The toolbar.
 */
export function ActiveFieldToolbar({ children }: { children: ReactNode }) {
  const active = useContext(ActiveFieldContext);
  const shown = active !== false;

  // Pressing a button must not take focus from the editor: the toolbar would hide, and the selection would be lost.
  function keepEditorFocus(event: MouseEvent<HTMLDivElement>) {
    if (event.target instanceof Element && event.target.closest("button")) event.preventDefault();
  }

  return (
    <div onMouseDown={keepEditorFocus} style={shown ? undefined : { visibility: "hidden" }} data-active-field-toolbar={shown ? "shown" : "hidden"}>
      {children}
    </div>
  );
}
