/**
 * Module: components/TagInput
 *
 * The tag picker: the chosen tags as removable chips followed by one text box. Typing filters
 * the vocabulary; Enter, a click, a comma or a semicolon adds the highlighted (or typed) tag.
 *
 * Responsibilities:
 * - In a free project, offer "Add tag ..." for a name the vocabulary does not have.
 * - In a restricted project, accept only names the vocabulary offers (picker only) and say who
 *   can add a missing one.
 * - Validate a typed name with the same rules as the server (`tagNameProblem`).
 * - Report each change through `onChange`; nothing is saved here.
 *
 * Design decisions: names are compared case-insensitively, as the server does, so picking
 * `safety` when `Safety` is listed uses the listed spelling. The chips keep their vocabulary
 * colour. Enter never submits a surrounding form while the list is open or text is typed.
 */
import { useId, useMemo, useState, type KeyboardEvent } from "react";

import { normaliseTagName, tagNameProblem, TAG_NAME_MAX_LENGTH, type TagChipData } from "../api/tags";
import { useStrings } from "../context/TerminologyContext";
import { TagChip } from "./TagChip";

const key = (name: string) => normaliseTagName(name).toLowerCase();

/**
 * @param value The chosen tag names.
 * @param onChange Called with the new list after an add or a removal.
 * @param suggestions The vocabulary to pick from (with colours).
 * @param restricted True when only listed tags may be applied.
 * @param label Accessible name of the text box.
 * @param disabled Show the chips without the box and remove controls.
 */
export function TagInput({
  value, onChange, suggestions, restricted = false, label, disabled = false,
}: {
  value: string[];
  onChange: (names: string[]) => void;
  suggestions: TagChipData[];
  restricted?: boolean;
  label?: string;
  disabled?: boolean;
}) {
  const strings = useStrings();
  const listboxId = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const [problem, setProblem] = useState<string | null>(null);

  const colourOf = useMemo(() => new Map(suggestions.map((t) => [key(t.name), t.colour])), [suggestions]);
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
    <div className="stack" style={{ gap: "0.25rem" }}>
      <div className="row" style={{ gap: "0.35rem", alignItems: "center" }}>
        {value.length === 0 && disabled && <span className="text-muted">{strings.tags.none}</span>}
        {value.map((name) => (
          <TagChip
            key={key(name)}
            tag={{ name, colour: colourOf.get(key(name)) ?? null }}
            removeLabel={strings.tags.removeLabel(name)}
            onRemove={disabled ? undefined : () => onChange(value.filter((n) => key(n) !== key(name)))}
          />
        ))}
        {!disabled && (
          <div style={{ position: "relative", flex: "1 1 10rem", minWidth: "8rem" }}>
            <input
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
                className="card stack"
                style={{
                  position: "absolute", top: "100%", left: 0, right: 0, zIndex: 10, marginTop: "0.25rem",
                  padding: "0.25rem", gap: "0.15rem", maxHeight: 220, overflowY: "auto",
                }}
              >
                {options.length === 0 && (
                  <span className="text-muted" style={{ padding: "0.35rem 0.5rem" }}>{strings.tags.noMatches}</span>
                )}
                {options.map((option, i) => (
                  <button
                    key={`${option.create ? "new" : "tag"}-${option.name}`}
                    id={`${listboxId}-option-${i}`}
                    role="option"
                    aria-selected={i === highlighted}
                    type="button"
                    className="btn"
                    style={{
                      border: "none", justifyContent: "flex-start", textAlign: "left", whiteSpace: "normal",
                      background: i === highlighted ? "var(--color-surface-alt)" : undefined,
                    }}
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
          </div>
        )}
      </div>
      {problem && <span role="alert" style={{ fontSize: "0.8rem", color: "var(--color-danger)" }}>{problem}</span>}
    </div>
  );
}
