/**
 * Module: modules/architecture/SymbolPicker
 *
 * A form field that chooses a symbol from a library (the type form and the element form share it), with a preview
 * of the choice. An empty choice means "use the default": for a type, its shape; for an element, its type's symbol.
 * The caller supplies the symbols and the path each is read from, so the picker works for a project's library
 * and an organisation's alike.
 */
import { LabeledSelect } from "../../components/LabeledSelect";
import { SymbolImage } from "./SymbolImage";
import type { ArchitectureSymbol } from "./types";

/**
 * @param label The field caption.
 * @param symbols The symbols that may be chosen.
 * @param value The chosen symbol's id, or `null` for none.
 * @param onChange Called with the chosen id, or `null` to clear.
 * @param urlFor The API path of a symbol's content.
 * @param emptyLabel Text of the "none" choice (what the default is).
 */
export function SymbolPicker({
  label, symbols, value, onChange, urlFor, emptyLabel, help,
}: {
  label: string;
  /** The field's `(?)` help text. */
  help: string;
  symbols: ArchitectureSymbol[];
  value: string | null;
  onChange: (next: string | null) => void;
  urlFor: (symbolId: string) => string;
  emptyLabel: string;
}) {
  const chosen = symbols.find((s) => s.id === value);
  return (
    <div className="row" style={{ gap: "var(--space-3)", alignItems: "flex-end" }}>
      <div style={{ flex: 1 }}>
        <LabeledSelect
          help={help}
          label={label}
          value={value ?? ""}
          onChange={(next) => onChange(next || null)}
          options={symbols.map((s) => ({ value: s.id, label: s.name }))}
          placeholder={emptyLabel}
        />
      </div>
      {chosen && <SymbolImage src={urlFor(chosen.id)} alt={`Preview of ${chosen.name}`} size={40} />}
    </div>
  );
}
