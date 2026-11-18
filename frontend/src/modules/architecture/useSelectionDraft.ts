/**
 * Module: modules/architecture/useSelectionDraft
 *
 * The draft behind a Selection card that edits a record in place (`StateSelectionFields`, `TransitionSelectionFields`): the values
 * being typed, the fields that differ from what is stored, and a commit that stores only those fields.
 *
 * Design decisions:
 * - Content is stored at once, not with the drawing, so the draft lives only until it is stored; `onSave` resolves false for a
 *   refusal, which leaves the draft for correction.
 * - A read that brings new stored values replaces only the fields the person has not changed since the previous read, so another
 *   save's changes are taken in and a field being edited is kept.
 * - One commit runs at a time, so a blur and a Save press together store once.
 */
import { useRef, useState } from "react";

/**
 * @param stored The record's values as last read.
 * @param diff The fields whose value differs between two value sets.
 * @param normalise Applied to the draft before it is compared and stored (for example trimming a name).
 * @param refuse True when the draft must not be stored yet (a required field left blank); `refused` then reads true until a field changes.
 * @param onSave Stores the changed fields; resolves true when stored.
 * @returns The draft, a field setter, whether anything differs, whether a commit was refused, and the commit.
 */
export function useSelectionDraft<T extends object>({
  stored, diff, normalise = (values) => values, refuse, onSave,
}: {
  stored: T;
  diff: (before: T, after: T) => Partial<T>;
  normalise?: (values: T) => T;
  refuse?: (values: T) => boolean;
  onSave: (changed: Partial<T>) => Promise<boolean>;
}) {
  const [draft, setDraft] = useState<T>(stored);
  const [seen, setSeen] = useState<T>(stored);
  const [refused, setRefused] = useState(false);
  const saving = useRef(false);

  if (Object.keys(diff(seen, stored)).length > 0) {
    setSeen(stored);
    setDraft((d) => {
      const next = { ...stored };
      (Object.keys(d) as (keyof T)[]).forEach((key) => {
        if (d[key] !== seen[key]) next[key] = d[key];
      });
      return next;
    });
  }

  const changed = diff(stored, normalise(draft));
  const hasChanges = Object.keys(changed).length > 0;
  const set = <K extends keyof T>(key: K, value: T[K]) => {
    setRefused(false);
    setDraft((d) => ({ ...d, [key]: value }));
  };

  async function commit() {
    if (saving.current || !hasChanges) return;
    if (refuse?.(draft)) {
      setRefused(true);
      return;
    }
    saving.current = true;
    try {
      await onSave(changed);
    } finally {
      saving.current = false;
    }
  }

  return { draft, set, hasChanges, refused, commit };
}
