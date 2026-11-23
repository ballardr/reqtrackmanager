/**
 * Module: components/TagAddBox
 *
 * The box that adds tags: one text box over a list of matching vocabulary tags. Typing filters the vocabulary and Enter,
 * a click, a comma or a semicolon adds the highlighted (or typed) tag. It is the content of the popover of `TagInput` (a
 * create form) and of the record header's "Add tag" popover (`RecordTags`), so the two cannot drift.
 *
 * Responsibilities: in a free project offer "Add tag ..." for a name the vocabulary lacks; in a restricted project
 * accept only listed names and say who can add a missing one; validate a typed name as the server does
 * (`tagNameProblem`); report each change through `onChange` (nothing is saved here).
 *
 * Design decisions: the box stays open after each add (cleared and refocused) so several tags go in one visit; Escape
 * closes the suggestion list first, then bubbles to the popover. Names compare case-insensitively as on the server, so
 * `safety` picks the listed `Safety`. Enter never submits a surrounding form (the popover is portalled outside it).
 */
import { useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { normaliseTagName, tagNameProblem, TAG_NAME_MAX_LENGTH, type TagChipData } from "../api/tags";
import { useStrings } from "../context/TerminologyContext";

const key = (name: string) => normaliseTagName(name).toLowerCase();

/**
 * @param value The chosen tag names.
 * @param onChange Called with the new list after an add or (Backspace in an empty box) a removal of the last tag.
 * @param suggestions The vocabulary to pick from (with colours).
 * @param restricted True when only listed tags may be applied.
 * @param onDone Closes the popover that holds the box (the Done button).
 * @param label Accessible name of the text box.
 */
export function TagAddBox({
  value, onChange, suggestions, restricted = false, onDone, label,
}: {
  value: string[];
  onChange: (names: string[]) => void;
  suggestions: TagChipData[];
  restricted?: boolean;
  onDone: () => void;
  label?: string;
}) {
  const strings = useStrings();
  const listboxId = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const [problem, setProblem] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const chosen = useMemo(() => new Set(value.map(key)), [value]);
  const trimmed = normaliseTagName(query);
  const matches = useMemo(
    () => suggestions.filter((t) => !chosen.has(key(t.name)) && key(t.name).includes(trimmed.toLowerCase())),
    [suggestions, chosen, trimmed],
  );
  const exact = suggestions.find((t) => key(t.name) === trimmed.toLowerCase());
  const canCreate = !restricted && trimmed !== "" && !exact && !chosen.has(trimmed.toLowerCase());
  // The options the list shows, in order: matching vocabulary tags, then the "Add tag" row.
  const options: Array<{ name: string; create: boolean }> = [
    ...matches.map((t) => ({ name: t.name, create: false })),
    ...(canCreate ? [{ name: trimmed, create: true }] : []),
  ];

  function add(raw: string) {
    const bad = tagNameProblem(raw);
    if (bad) {
      setProblem(
        bad === "empty" ? strings.tags.empty
          : bad === "too_long" ? strings.tags.tooLong(TAG_NAME_MAX_LENGTH)
          : strings.tags.invalidCharacters,
      );
      return;
    }
    const name = normaliseTagName(raw);
    const listed = suggestions.find((t) => key(t.name) === key(name));
    if (restricted && !listed && !chosen.has(key(name))) {
      setProblem(strings.tags.notListed);
      return;
    }
    if (!chosen.has(key(name))) onChange([...value, listed ? listed.name : name]);
    setQuery("");
    setProblem(null);
    setHighlighted(-1);
    setOpen(false);
    // The popover stays open so several tags go in one visit.
    inputRef.current?.focus();
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      // Enter in a text field would otherwise submit the surrounding form.
      if (open && highlighted >= 0 && highlighted < options.length) {
        e.preventDefault();
        add(options[highlighted].name);
      } else if (trimmed !== "") {
        e.preventDefault();
        add(trimmed);
      } else if (open) {
        e.preventDefault();
      }
    } else if (e.key === "," || e.key === ";") {
      e.preventDefault();
      if (trimmed !== "") add(trimmed);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) setOpen(true);
      else if (options.length > 0) setHighlighted((i) => (i + 1) % options.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (options.length > 0) setHighlighted((i) => (i - 1 + options.length) % options.length);
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
      setHighlighted(-1);
    } else if (e.key === "Backspace" && query === "" && value.length > 0) {
      onChange(value.slice(0, -1));
    }
  }

  return (
    <div className="stack" style={{ gap: "var(--space-2)", minWidth: "14rem" }}>
      <input
        ref={inputRef}
        className="input"
        role="combobox"
        aria-label={label ?? strings.tags.label}
        aria-expanded={open && options.length > 0}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-activedescendant={open && highlighted >= 0 ? `${listboxId}-option-${highlighted}` : undefined}
        aria-invalid={problem ? true : undefined}
        placeholder={restricted ? strings.tags.inputPlaceholderRestricted : strings.tags.inputPlaceholder}
        value={query}
        maxLength={TAG_NAME_MAX_LENGTH * 2}
        autoFocus
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setHighlighted(-1);
          setProblem(null);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        onKeyDown={onKeyDown}
      />
      {open && (
        <div
          id={listboxId}
          role="listbox"
          aria-label={strings.tags.listLabel}
          className="stack scroll-region"
          style={{ gap: "0.15rem", maxHeight: 220 }}
        >
          {options.length === 0 && (
            <span className="text-muted" style={{ padding: "var(--space-2) var(--space-3)" }}>{strings.tags.noMatches}</span>
          )}
          {options.map((option, i) => (
            <button
              key={`${option.create ? "new" : "tag"}-${option.name}`}
              id={`${listboxId}-option-${i}`}
              role="option"
              aria-selected={i === highlighted}
              type="button"
              className="menu-item"
              onMouseEnter={() => setHighlighted(i)}
              // mousedown, not click: the input's blur would close the list before a click lands.
              onMouseDown={(e) => {
                e.preventDefault();
                add(option.name);
              }}
            >
              {option.create ? strings.tags.createOption(option.name) : option.name}
            </button>
          ))}
        </div>
      )}
      {problem && <span role="alert" style={{ fontSize: "0.8rem", color: "var(--color-danger)" }}>{problem}</span>}
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button type="button" className="btn btn-sm" onClick={onDone}>{strings.tags.done}</button>
      </div>
    </div>
  );
}
