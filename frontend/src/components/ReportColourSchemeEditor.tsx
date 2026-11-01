/**
 * Module: components/ReportColourSchemeEditor
 *
 * Edits a colour scheme: up to eight named colours that blocks use by name (`primary`, `warning`), so one change re-colours
 * everything that uses the name. It serves two places: a layout's own scheme (Layout settings) and the organisation's scheme
 * (the Branding page), which a layout without a scheme of its own follows.
 *
 * Responsibilities:
 * - List the colours as `ItemRowList` rows (name, the colour it resolves to, a gear for the name and colour, remove).
 * - Layout only: say whether the layout follows the organisation's colours, offer **Start from** (one-shot fills) and
 *   **Follow the organisation's colours** (clears the layout's own).
 * - Refuse to remove, rename, or drop (by starting over or following) a name a block still uses, and say why.
 *
 * Design decisions: a name is the link between a block and its colour, so a used name is fixed; the server also reports
 * a name that no longer resolves. The colour of an entry points at a colour (hex or the branding colour's forms), never
 * at another name, matching the server's rule that resolution is one step. The settings sit in a popover that holds the
 * choice list inline, so popovers do not nest.
 */
import { X } from "lucide-react";
import { useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import {
  MAX_SCHEME_COLOURS, SCHEME_STARTS, freshColourName, isColourName, resolveColourWord, type ColourContext, type ColourEntry,
} from "../utils/reportColours";
import { ColourChoiceList, ColourSwatch } from "./ColourChoiceField";
import { TextField } from "./FormFields";
import { ItemRowList } from "./ItemRowList";
import { LabeledSelect } from "./LabeledSelect";
import { SettingsPopoverButton } from "./SettingsPopoverButton";

/**
 * @param value The scheme's colours as stored (empty: a layout follows the organisation's).
 * @param onChange Called with the edited colours; an empty list means none (a layout then follows the organisation's).
 * @param context The branding colour and the organisation's scheme.
 * @param mode `layout` for a layout's own scheme, `organization` for the organisation's.
 * @param used Names a block of the layout uses (layout mode), which cannot be removed or renamed.
 * @param disabled Read-only.
 */
export function ReportColourSchemeEditor({
  value, onChange, context, mode, used = new Set<string>(), disabled = false,
}: {
  value: ColourEntry[];
  onChange: (next: ColourEntry[]) => void;
  context: ColourContext;
  mode: "layout" | "organization";
  used?: Set<string>;
  disabled?: boolean;
}) {
  const strings = useStrings();
  const text = strings.reportColours;
  const [fresh, setFresh] = useState<number | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const names = value.map((e) => e.name);
  const layout = mode === "layout";

  function patch(i: number, change: Partial<ColourEntry>) {
    setRefusal(null);
    onChange(value.map((e, j) => (j === i ? { ...e, ...change } : e)));
  }

  function remove(i: number) {
    const name = value[i].name;
    if (used.has(name)) {
      setRefusal(text.removeRefused(name));
      return;
    }
    setRefusal(null);
    onChange(value.filter((_, j) => j !== i));
  }

  function add() {
    setRefusal(null);
    setFresh(value.length);
    onChange([...value, { name: freshColourName(names), colour: "accent" }]);
  }

  /** Replaces the scheme with a starting set, keeping any used name the set lacks so no block loses its colour. */
  function startFrom(key: string) {
    const set = key === "organisation" ? context.organization_scheme : SCHEME_STARTS[key];
    if (!set) return;
    const kept = value.filter((e) => used.has(e.name) && !set.some((s) => s.name === e.name));
    setRefusal(null);
    onChange([...set, ...kept].slice(0, MAX_SCHEME_COLOURS));
  }

  /** Clears the layout's own colours, unless a block uses a name only they define. */
  function follow() {
    const stranded = value.find((e) => used.has(e.name) && !context.organization_scheme.some((o) => o.name === e.name)
      && !context.standard.some((s) => s.name === e.name));
    if (stranded) {
      setRefusal(text.removeRefused(stranded.name));
      return;
    }
    setRefusal(null);
    onChange([]);
  }

  function nameProblem(i: number): string | null {
    const name = value[i].name;
    if (!isColourName(name)) return text.nameInvalid;
    if (names.some((n, j) => j !== i && n === name)) return text.nameTaken;
    return null;
  }

  const rows = value.map((entry, i) => {
    const shown = entry.name || text.emptyName;
    const hex = resolveColourWord(entry.colour, context);
    return {
      id: String(i),
      name: entry.name,
      detail: hex ?? undefined,
      actions: (
        <>
          <ColourSwatch hex={hex} />
          <SettingsPopoverButton label={text.settingsFor(shown)} title={text.settingsFor(shown)} defaultOpen={fresh === i}>
            <div className="stack" style={{ gap: "var(--space-2)" }}>
              <TextField
                label={text.nameLabel} value={entry.name} disabled={disabled || used.has(entry.name)} help={strings.help.colourSchemeName}
                onChange={(name) => patch(i, { name })} inputProps={{ maxLength: 24, spellCheck: false }}
                hint={used.has(entry.name) ? text.removeRefused(entry.name) : undefined}
              />
              {nameProblem(i) && <span role="alert" style={{ fontSize: "0.8rem", color: "var(--color-danger)" }}>{nameProblem(i)}</span>}
              <span className="stack" style={{ gap: "var(--space-1)" }}>
                <span>{text.colourLabel}</span>
                {!disabled && (
                  <ColourChoiceList
                    value={entry.colour} name={`${text.colourLabel} ${shown}`} context={context} allowNone={false} allowNames={false}
                    onChoose={(colour) => patch(i, { colour })}
                  />
                )}
              </span>
            </div>
          </SettingsPopoverButton>
          {!disabled && (
            <button type="button" className="btn btn-sm btn-icon" aria-label={text.removeColour(shown)} title={text.removeColour(shown)} onClick={() => remove(i)}>
              <X size={14} aria-hidden="true" />
            </button>
          )}
        </>
      ),
    };
  });

  const starts = [
    ...(layout && context.organization_scheme.length > 0 ? ["organisation"] : []),
    ...Object.keys(SCHEME_STARTS),
  ];

  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      {layout && <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>{value.length === 0 ? text.followingOrganisation : text.ownScheme}</p>}
      {!layout && <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>{text.organisationSchemeHint}</p>}
      {rows.length > 0 && <ItemRowList items={rows} label={text.schemeList} emptyName={text.emptyName} />}
      {refusal && <span role="alert" style={{ fontSize: "0.85rem", color: "var(--color-danger)" }}>{refusal}</span>}
      {!disabled && (
        <div className="row" style={{ gap: "var(--space-2)", alignItems: "flex-end", flexWrap: "wrap" }}>
          <button type="button" className="btn btn-sm" disabled={value.length >= MAX_SCHEME_COLOURS} onClick={add}>{text.addColour}</button>
          {value.length >= MAX_SCHEME_COLOURS && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{text.tooMany}</span>}
          {layout && (
            <>
              <LabeledSelect
                label={text.startFrom} value="" placeholder={text.startChoose} help={strings.help.colourSchemeStart}
                options={starts.map((key) => ({ value: key, label: text.starts[key] ?? key }))} onChange={startFrom}
              />
              {value.length > 0 && <button type="button" className="btn btn-sm" onClick={follow}>{text.followOrganisation}</button>}
            </>
          )}
        </div>
      )}
    </div>
  );
}
