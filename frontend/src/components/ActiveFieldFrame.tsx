/**
 * Module: components/ActiveFieldFrame
 *
 * The frame of a rich text field (the Markdown editor's Visual and Write views, the policy editor) that shows the
 * field's controls (its formatting toolbar and its view switch) only while the person is working in it.
 *
 * Responsibilities:
 * - Track whether the field is in use (focus is anywhere inside it: the editor, the toolbar buttons, the link entry,
 *   the view switch, a panel opened from the toolbar) and tell `ActiveFieldToolbar` through context.
 * - Draw a control slot that is absent while the field is not in use (the toolbar row), or that keeps its place and
 *   is hidden (`reserveSpace`, the view switch in the caption line); a hidden control is out of the tab order and the
 *   accessibility tree either way.
 * - Keep focus in the editor when a toolbar button is pressed, so pressing a button does not end the use of the field
 *   (some browsers do not focus a button on click) and the selection survives.
 *
 * Design decisions:
 * - Focus within the frame decides, not the pointer (a touch screen has no hover) and not the editor alone (pressing
 *   a button moves focus to the button). Focus moving between two controls, or into a panel drawn outside the frame's
 *   element but inside it in the component tree, is not leaving: a blur is settled after the focus that follows it.
 * - A field gains its toolbar row when it is first used, which moves the text below it down. When the pointer is
 *   pressed at that moment the row is drawn on release, so the movement never happens between the press and the
 *   release of the click that placed the caret or started a selection.
 * - The caption-line view switch reserves its place, so nothing moves in any view. The toolbar row does not: an
 *   unused field takes no room for controls (decided by the user).
 * - A frame inside another frame tracks nothing, so the field's own frame decides for the editor nested in it.
 * - There is no setting to keep the controls always visible: one rule for every rich text field.
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState, type CSSProperties, type MouseEvent, type ReactNode } from "react";

/** Whether focus is inside the nearest frame; null outside any frame. */
const ActiveFieldContext = createContext<boolean | null>(null);

/**
 * @param children The field: its editor, its view switch and its `ActiveFieldToolbar` slots.
 * @param className The frame's class (the field's own layout).
 * @param style The frame's inline style.
 * @returns The field wrapped so that focus inside it is tracked.
 */
export function ActiveFieldFrame({ children, className, style }: { children: ReactNode; className?: string; style?: CSSProperties }) {
  const outer = useContext(ActiveFieldContext);
  const [active, setActive] = useState(false);
  const focusInside = useRef(false);
  const pointerDown = useRef(false);
  const settle = useRef<ReturnType<typeof setTimeout> | null>(null);
  const release = useRef<(() => void) | null>(null);
  const frame = useRef<HTMLDivElement>(null);

  const enter = useCallback(() => {
    focusInside.current = true;
    if (settle.current) clearTimeout(settle.current);
    settle.current = null;
    if (!pointerDown.current) setActive(true);
  }, []);

  const leave = useCallback(() => {
    focusInside.current = false;
    if (settle.current) clearTimeout(settle.current);
    // Focus that moves to another control of the field raises its focus event right after this blur, so the field is
    // left only if none followed.
    settle.current = setTimeout(() => {
      settle.current = null;
      if (!focusInside.current) setActive(false);
    }, 0);
  }, []);

  /** Notes a pressed pointer until it is released; a field first used by that press is drawn active on release. */
  const trackPointer = useCallback(() => {
    if (pointerDown.current) return;
    pointerDown.current = true;
    const types = ["pointerup", "pointercancel", "mouseup", "dragend"];
    const done = () => {
      pointerDown.current = false;
      release.current = null;
      for (const type of types) document.removeEventListener(type, done, true);
      if (focusInside.current) setActive(true);
    };
    release.current = done;
    for (const type of types) document.addEventListener(type, done, true);
  }, []);

  useEffect(() => {
    // The focused control can be removed without a blur (a view that replaces the editor), which would leave the field
    // in use; the next focus that lands outside the frame ends it. A control drawn outside the frame's element for the
    // frame (a panel) raises its own focus event in the component tree right after, which cancels this.
    const onFocusElsewhere = (event: FocusEvent) => {
      if (focusInside.current && frame.current && event.target instanceof Node && !frame.current.contains(event.target)) leave();
    };
    document.addEventListener("focusin", onFocusElsewhere, true);
    return () => {
      document.removeEventListener("focusin", onFocusElsewhere, true);
      if (settle.current) clearTimeout(settle.current);
      release.current?.();
    };
  }, [leave]);

  // Nested in a field's frame: that frame decides, so this one only supplies the layout.
  if (outer !== null) return <div className={className} style={style}>{children}</div>;

  return (
    <ActiveFieldContext.Provider value={active}>
      <div ref={frame} className={className} style={style} onPointerDownCapture={trackPointer} onFocus={enter} onBlur={leave}>
        {children}
      </div>
    </ActiveFieldContext.Provider>
  );
}

/**
 * The slot a toolbar (or other field control) is drawn in: shown while the field is in use. While it is not, the slot
 * is absent (the field takes no room for it), or, with `reserveSpace`, hidden but keeping its place so nothing around
 * it moves. Outside any frame the content is always shown.
 *
 * @param children The control.
 * @param reserveSpace Keep the slot's place while hidden (a control in a line that exists anyway, such as a caption).
 */
export function ActiveFieldToolbar({ children, reserveSpace }: { children: ReactNode; reserveSpace?: boolean }) {
  const active = useContext(ActiveFieldContext);
  const shown = active !== false;
  if (!shown && !reserveSpace) return null;

  // Pressing a toolbar button must not take focus from the editor: the field would stop being in use, and the selection would be lost.
  function keepEditorFocus(event: MouseEvent<HTMLDivElement>) {
    if (event.target instanceof Element && event.target.closest("button")) event.preventDefault();
  }

  return (
    <div onMouseDown={keepEditorFocus} style={shown ? undefined : { visibility: "hidden" }} data-active-field-toolbar={shown ? "shown" : "hidden"}>
      {children}
    </div>
  );
}
