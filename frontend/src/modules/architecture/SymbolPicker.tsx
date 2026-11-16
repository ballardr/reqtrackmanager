/**
 * Module: modules/architecture/SymbolPicker
 *
 * A form field that chooses a symbol from a library (the type form and the element form share it), with a preview
 * of the choice. An empty choice means "use the default": for a type, its shape; for an element, its type's symbol.
 * The caller supplies the symbols and the path each is read from, so the picker works for a project's library
 * and an organisation's alike.
 *
 * Two views, switched by a per-person toggle kept in browser storage: List (a select of names) and Gallery (a popover
 * grid that shows the drawings, `SymbolGallery`). A person who may change the library (the capabilities read; the server
 * still enforces the role) also sees an upload control in either view: the file joins the shared library and is chosen
 * in the form's draft, saved with the form. Symbols uploaded here are remembered locally so they can be chosen before the
 * caller has reloaded its list.
 */
import { LayoutGrid, List } from "lucide-react";
import { useId, useRef, useState } from "react";

import { FieldShell } from "../../components/FieldHelp";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Popover } from "../../components/Popover";
import { ToggleButton } from "../../components/ToggleButton";
import type { TypesScope } from "./ArchitectureTypesPanel";
import { ARCHITECTURE_HELP } from "./help";
import { SymbolGallery } from "./SymbolGallery";
import { SymbolImage } from "./SymbolImage";
import { SymbolUploadField } from "./SymbolUploadField";
import type { ArchitectureSymbol } from "./types";
import { useCanUploadSymbols, useSymbolUpload } from "./useSymbolUpload";

type PickerView = "list" | "gallery";
const VIEW_STORAGE_KEY = "architecture.symbolPickerView";

/** The remembered view; List when nothing is stored or storage is unavailable (a private window, blocked site data). */
function readView(): PickerView {
  try {
    return window.localStorage.getItem(VIEW_STORAGE_KEY) === "gallery" ? "gallery" : "list";
  } catch {
    return "list";
  }
}

/** Remembers the view; a storage failure only means it is not remembered. */
function writeView(view: PickerView) {
  try {
    window.localStorage.setItem(VIEW_STORAGE_KEY, view);
  } catch {
    // Not remembered; the picker works the same.
  }
}

/** The upload control with its own upload state, rendered only for a person who may upload. */
function PickerUpload({ scope, onUploaded }: { scope: TypesScope; onUploaded: (symbol: ArchitectureSymbol) => void }) {
  const id = useId();
  const state = useSymbolUpload(scope, onUploaded, "Symbol uploaded and chosen. Save to keep the choice.");
  return <SymbolUploadField id={`symbol-picker-upload-${id}`} state={state} help={ARCHITECTURE_HELP.symbolPickerUpload} />;
}

/**
 * @param label The field caption.
 * @param symbols The symbols that may be chosen.
 * @param value The chosen symbol's id, or `null` for none.
 * @param onChange Called with the chosen id, or `null` to clear.
 * @param urlFor The API path of a symbol's content.
 * @param emptyLabel Text of the "none" choice (what the default is).
 * @param scope The library's owner, for the upload control; omit for a picker that cannot upload.
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
  const [view, setView] = useState<PickerView>(readView);
  const [open, setOpen] = useState(false);
  const [added, setAdded] = useState<ArchitectureSymbol[]>([]);
  const trigger = useRef<HTMLButtonElement>(null);
  const triggerId = useId();
  const canUpload = useCanUploadSymbols(scope);

  const all = [...symbols, ...added.filter((a) => !symbols.some((s) => s.id === a.id))];
  const chosen = all.find((s) => s.id === value);

  function chooseView(next: PickerView) {
    setView(next);
    setOpen(false);
    writeView(next);
  }

  function uploaded(symbol: ArchitectureSymbol) {
    setAdded((current) => [...current, symbol]);
    onChange(symbol.id);
    onSymbolsChanged?.();
    setOpen(false);
  }

  const upload = canUpload && scope ? <PickerUpload scope={scope} onUploaded={uploaded} /> : null;

  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      <div className="row" style={{ gap: "var(--space-3)", alignItems: "flex-end" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {view === "list" ? (
            <LabeledSelect
              help={help}
              label={label}
              value={value ?? ""}
              onChange={(next) => onChange(next || null)}
              options={all.map((s) => ({ value: s.id, label: s.name }))}
              placeholder={emptyLabel}
            />
          ) : (
            <FieldShell label={label} controlId={triggerId} help={help}>
              <button
                id={triggerId} ref={trigger} type="button" className="input" aria-haspopup="dialog" aria-expanded={open}
                aria-label={`${label}: ${chosen ? chosen.name : emptyLabel}`}
                onClick={() => setOpen((current) => !current)} style={{ textAlign: "left", cursor: "pointer" }}
              >
                {chosen ? chosen.name : emptyLabel}
              </button>
            </FieldShell>
          )}
        </div>
        {chosen && <SymbolImage src={urlFor(chosen.id)} alt={`Preview of ${chosen.name}`} size={40} />}
        <div role="group" aria-label="Symbol view" className="row" style={{ gap: "var(--space-1)" }}>
          <ToggleButton label="List" pressed={view === "list"} onClick={() => chooseView("list")} help={ARCHITECTURE_HELP.symbolPickerView}>
            <List />
          </ToggleButton>
          <ToggleButton label="Gallery" pressed={view === "gallery"} onClick={() => chooseView("gallery")} help={ARCHITECTURE_HELP.symbolPickerView}>
            <LayoutGrid />
          </ToggleButton>
        </div>
      </div>
      {view === "list" && upload}
      {view === "gallery" && open && (
        <Popover anchorRef={trigger} onClose={() => setOpen(false)} title={`Choose ${label.toLowerCase()}`} matchAnchor>
          <SymbolGallery
            symbols={all} value={value} urlFor={urlFor} emptyLabel={emptyLabel} upload={upload}
            onChoose={(next) => { onChange(next); setOpen(false); }}
          />
        </Popover>
      )}
    </div>
  );
}
