/**
 * Module: hooks/useTextSelections
 *
 * Remembers the selection of one or more text inputs (a header's three cells, a block's text field) so an action
 * button pressed outside the input (a Bold button, a placeholder menu) can still act on the words the author selected.
 *
 * Design decisions: the selection is read on every selection change and on leaving the input, because pressing a
 * button or opening a menu moves the focus first. State is kept in refs, not React state, since a selection change
 * must not re-render the form. A mark writes the new text through the caller's setter and puts the selection back on
 * the wrapped words once the new text is in the input, so the next press acts on what the author sees.
 */
import { useRef, type SyntheticEvent } from "react";

import { insertAtCaret, wrapMark, wrapWholeText } from "../utils/reportPageSetup";

type Field = HTMLInputElement | HTMLTextAreaElement;
type Range = { start: number; end: number };

/** What the hook returns. `K` is the key of an input (a cell name, a field key). */
export interface TextSelections<K extends string> {
  /** `onSelect` / `onBlur` handler for the input named `key`. */
  remember: (key: K) => (e: SyntheticEvent<Field>) => void;
  /** Wraps the remembered selection of `key` in `marker` (`**` or `*`; the whole text when nothing is selected) and writes it through `write`. */
  mark: (key: K, current: string, marker: string, write: (next: string) => void) => void;
  /** Writes `snippet` over the remembered selection of `key`, with the caret after it, through `write`. */
  insert: (key: K, current: string, snippet: string, write: (next: string) => void) => void;
}

/**
 * @returns The selection reader and its actions (mark, insert); see {@link TextSelections}.
 */
export function useTextSelections<K extends string>(): TextSelections<K> {
  const caret = useRef<Partial<Record<K, Range>>>({});
  const fields = useRef<Partial<Record<K, Field>>>({});
  const remember = (key: K) => (e: SyntheticEvent<Field>) => {
    fields.current[key] = e.currentTarget;
    caret.current[key] = { start: e.currentTarget.selectionStart ?? 0, end: e.currentTarget.selectionEnd ?? 0 };
  };
  /** Writes `next` and, once it is in the input, puts the selection back so the next press acts on what the author sees. */
  const apply = (key: K, next: string, start: number, end: number, write: (text: string) => void) => {
    caret.current[key] = { start, end };
    write(next);
    requestAnimationFrame(() => {
      fields.current[key]?.focus();
      fields.current[key]?.setSelectionRange(start, end);
    });
  };
  const at = (key: K, current: string): Range => caret.current[key] ?? { start: current.length, end: current.length };
  const mark = (key: K, current: string, marker: string, write: (next: string) => void) => {
    const range = at(key, current);
    // Nothing selected marks the whole box; a selection marks just those words.
    const next = range.start === range.end ? wrapWholeText(current, marker) : wrapMark(current, marker, range.start, range.end);
    apply(key, next.text, next.start, next.end, write);
  };
  const insert = (key: K, current: string, snippet: string, write: (next: string) => void) => {
    const range = at(key, current);
    const next = insertAtCaret(current, snippet, range.start, range.end);
    apply(key, next.text, next.caret, next.caret, write);
  };
  return { remember, mark, insert };
}
