/**
 * Module: modules/architecture/SymbolPickerPanel
 *
 * The panel the symbol picker opens: a name filter above, the chosen view of the symbols in the middle and the view buttons
 * below (List, Gallery and, when the person may change the library, Upload), as an emoji picker lays them out. It owns the
 * filter text and nothing else: the view, the choice and the upload result belong to the picker.
 *
 * Design decisions:
 * - The panel has no width of its own: the popover is as wide as the field it opened from (never under its floor), so a
 *   fixed minimum here ran out of the bubble, the card and the window in a narrow Selection card.
 * - The filter is the first control, so the popover's own focus management puts the focus there on opening and a person can
 *   type at once; it is hidden in the Upload view, where it would filter nothing.
 * - The Upload view is only offered when `scope` is given, so a person who may not upload sees no such button (not a
 *   disabled one).
 *
 * Dependencies: `SymbolGallery`, `SymbolList`, `SymbolUploadField`, `useSymbolUpload`.
 */
import { LayoutGrid, List, Upload } from "lucide-react";
import { useId, useState } from "react";

import { InlineTextInput } from "../../components/FormFields";
import { ToggleButton } from "../../components/ToggleButton";
import type { TypesScope } from "./ArchitectureTypesPanel";
import { ARCHITECTURE_HELP } from "./help";
import { SymbolGallery } from "./SymbolGallery";
import { SymbolList } from "./SymbolList";
import { SymbolUploadField } from "./SymbolUploadField";
import type { ArchitectureSymbol } from "./types";
import { useSymbolUpload } from "./useSymbolUpload";

/** What the panel shows: the names, the drawings or the upload control. */
export type SymbolPickerView = "list" | "gallery" | "upload";

/** The Upload view: the file control with its own upload state. */
function UploadView({ scope, onUploaded }: { scope: TypesScope; onUploaded: (symbol: ArchitectureSymbol) => void }) {
  const id = useId();
  const state = useSymbolUpload(scope, onUploaded, "Symbol uploaded and chosen. Save to keep the choice.");
  return <SymbolUploadField id={`symbol-picker-upload-${id}`} state={state} help={ARCHITECTURE_HELP.symbolPickerUpload} />;
}

/**
 * @param symbols The symbols that may be chosen.
 * @param value The chosen symbol's id, or `null` for none.
 * @param urlFor The API path of a symbol's content.
 * @param emptyLabel The None choice's text (what the default is).
 * @param view The view shown.
 * @param onView Called with the view a button asked for.
 * @param scope The library's owner when the person may upload (the Upload button and view appear), else `null`.
 * @param onUploaded Called with a symbol just uploaded.
 * @param onChoose Called with the chosen id, or `null` for None.
 */
export function SymbolPickerPanel({
  symbols, value, urlFor, emptyLabel, view, onView, scope, onUploaded, onChoose,
}: {
  symbols: ArchitectureSymbol[];
  value: string | null;
  urlFor: (symbolId: string) => string;
  emptyLabel: string;
  view: SymbolPickerView;
  onView: (view: SymbolPickerView) => void;
  scope: TypesScope | null;
  onUploaded: (symbol: ArchitectureSymbol) => void;
  onChoose: (next: string | null) => void;
}) {
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();
  const shown = symbols.filter((s) => s.name.toLowerCase().includes(needle));
  const showing = view === "upload" && scope === null ? "list" : view;

  return (
    <div className="stack" style={{ gap: "var(--space-2)", minWidth: 0 }}>
      {showing !== "upload" && (
        <InlineTextInput ariaLabel="Filter symbols" placeholder="Search" value={filter} onChange={setFilter} />
      )}
      {showing === "gallery" && (
        <SymbolGallery symbols={shown} total={symbols.length} value={value} urlFor={urlFor} emptyLabel={emptyLabel} onChoose={onChoose} />
      )}
      {showing === "list" && <SymbolList symbols={shown} total={symbols.length} value={value} emptyLabel={emptyLabel} onChoose={onChoose} />}
      {showing === "upload" && scope && <UploadView scope={scope} onUploaded={onUploaded} />}
      <div role="group" aria-label="Symbol view" className="row" style={{ gap: "var(--space-1)", justifyContent: "center", flexWrap: "wrap" }}>
        <ToggleButton label="List" pressed={showing === "list"} onClick={() => onView("list")} help={ARCHITECTURE_HELP.symbolPickerList}>
          <List />
        </ToggleButton>
        <ToggleButton label="Gallery" pressed={showing === "gallery"} onClick={() => onView("gallery")} help={ARCHITECTURE_HELP.symbolPickerGallery}>
          <LayoutGrid />
        </ToggleButton>
        {scope && (
          <ToggleButton label="Upload" pressed={showing === "upload"} onClick={() => onView("upload")} help={ARCHITECTURE_HELP.symbolPickerUpload}>
            <Upload />
          </ToggleButton>
        )}
      </div>
    </div>
  );
}
