/**
 * Module: modules/architecture/SymbolPicker
 *
 * A form field that chooses a symbol from a library (shared by the type form and the element form). One button shows the
 * chosen symbol's drawing and name; an empty choice means "use the default" (a type's shape, an element's type symbol).
 * The caller supplies the symbols and each one's path, so it serves a project's and an organisation's library alike.
 * The button opens `SymbolPickerPanel`: List (names), Gallery (drawings) and, for a person who may change the library
 * (the server still enforces the role), Upload. List or Gallery is remembered per person in browser storage; Upload never.
 * An uploaded file is chosen in the form's draft and remembered locally so it can be chosen before the caller reloads its list.
 */
import { ChevronDown } from "lucide-react";
import { useId, useRef, useState } from "react";

import { FieldShell } from "../../components/FieldHelp";
import { Popover } from "../../components/Popover";
import type { TypesScope } from "./ArchitectureTypesPanel";
import { SymbolImage } from "./SymbolImage";
import { SymbolPickerPanel, type SymbolPickerView } from "./SymbolPickerPanel";
import type { ArchitectureSymbol } from "./types";
import { useCanUploadSymbols } from "./useSymbolUpload";

const VIEW_STORAGE_KEY = "architecture.symbolPickerView";

/** The remembered view; List when nothing is stored or storage is unavailable (a private window, blocked site data). */
function readView(): Exclude<SymbolPickerView, "upload"> {
  try {
    return window.localStorage.getItem(VIEW_STORAGE_KEY) === "gallery" ? "gallery" : "list";
  } catch {
    return "list";
  }
}

/** Remembers the view; a storage failure only means it is not remembered. */
function writeView(view: Exclude<SymbolPickerView, "upload">) {
  try {
    window.localStorage.setItem(VIEW_STORAGE_KEY, view);
  } catch {
    // Not remembered; the picker works the same.
  }
}

/**
 * @param label The field caption.
 * @param symbols The symbols that may be chosen.
 * @param value The chosen symbol's id, or `null` for none.
 * @param onChange Called with the chosen id, or `null` to clear.
 * @param urlFor The API path of a symbol's content.
 * @param emptyLabel Text of the "none" choice (what the default is).
 * @param scope The library's owner, for the Upload view; omit for a picker that cannot upload.
 * @param onSymbolsChanged Called after an upload so the caller reloads its symbols.
 */
export function SymbolPicker({
  label, symbols, value, onChange, urlFor, emptyLabel, help, scope = null, onSymbolsChanged,
}: {
  label: string;
  /** The field's `(?)` help text. */
  help: string;
  symbols: ArchitectureSymbol[];
  value: string | null;
  onChange: (next: string | null) => void;
  urlFor: (symbolId: string) => string;
  emptyLabel: string;
  scope?: TypesScope | null;
  onSymbolsChanged?: () => void;
}) {
  const [view, setView] = useState<SymbolPickerView>(readView);
  const [open, setOpen] = useState(false);
  const [added, setAdded] = useState<ArchitectureSymbol[]>([]);
  const trigger = useRef<HTMLButtonElement>(null);
  const triggerId = useId();
  const canUpload = useCanUploadSymbols(scope);

  const all = [...symbols, ...added.filter((a) => !symbols.some((s) => s.id === a.id))];
  const chosen = all.find((s) => s.id === value);

  function openPanel() {
    // Upload is a task, not a way of viewing, so each opening starts at the remembered List or Gallery.
    if (!open && view === "upload") setView(readView());
    setOpen((current) => !current);
  }

  function chooseView(next: SymbolPickerView) {
    setView(next);
    if (next !== "upload") writeView(next);
  }

  function uploaded(symbol: ArchitectureSymbol) {
    setAdded((current) => [...current, symbol]);
    onChange(symbol.id);
    onSymbolsChanged?.();
    setOpen(false);
  }

  return (
    <>
      <FieldShell label={label} controlId={triggerId} help={help}>
        <button
          id={triggerId} ref={trigger} type="button" className="input" aria-haspopup="dialog" aria-expanded={open}
          aria-label={`${label}: ${chosen ? chosen.name : emptyLabel}`} onClick={openPanel}
          style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", textAlign: "left", cursor: "pointer" }}
        >
          {chosen && <SymbolImage src={urlFor(chosen.id)} alt={`Preview of ${chosen.name}`} size={24} />}
          <span style={{ flex: 1, minWidth: 0 }}>{chosen ? chosen.name : emptyLabel}</span>
          <ChevronDown size={14} aria-hidden="true" />
        </button>
      </FieldShell>
      {open && (
        <Popover anchorRef={trigger} onClose={() => setOpen(false)} title={`Choose ${label.toLowerCase()}`} matchAnchor>
          <SymbolPickerPanel
            symbols={all} value={value} urlFor={urlFor} emptyLabel={emptyLabel} view={view} onView={chooseView}
            scope={canUpload ? scope : null} onUploaded={uploaded}
            onChoose={(next) => { onChange(next); setOpen(false); }}
          />
        </Popover>
      )}
    </>
  );
}
