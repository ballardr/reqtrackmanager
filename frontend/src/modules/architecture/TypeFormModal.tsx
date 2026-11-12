/**
 * Module: modules/architecture/TypeFormModal
 *
 * Create and edit dialog for an element type or a connection type, shared by the project and organisation panels
 * (and told apart from create by whether `initial` is passed, as the other module forms are). The two kinds share
 * the name, domain and colour pair; an element type adds a shape and a symbol, a connection type a line style and
 * whether it is one-way. Colours are optional and given for the light and the dark theme, so a type stays legible
 * in both.
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { ColorField, ToggleField, TextField } from "../../components/FormFields";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { labelOptions } from "../../utils/labelOptions";
import { ARCHITECTURE_HELP } from "./help";
import { SymbolPicker } from "./SymbolPicker";
import {
  DOMAIN_LABEL, ELEMENT_SHAPE_LABEL, LINE_STYLE_LABEL,
  type ArchitectureSymbol, type ConnectionType, type ConnectionTypeValues, type Domain, type ElementShape,
  type ElementType, type ElementTypeValues, type LineStyle,
} from "./types";

/** The fields of either kind in one draft; the unused kind's fields are never sent. */
interface Draft {
  name: string;
  domain: Domain;
  color_light: string;
  color_dark: string;
  shape: ElementShape;
  symbol_id: string | null;
  line_style: LineStyle;
  directional: boolean;
}

function blankDraft(): Draft {
  return {
    name: "", domain: "any", color_light: "", color_dark: "", shape: "rectangle", symbol_id: null,
    line_style: "solid", directional: true,
  };
}

function draftFrom(row: ElementType | ConnectionType): Draft {
  return {
    ...blankDraft(),
    name: row.name, domain: row.domain, color_light: row.color_light ?? "", color_dark: row.color_dark ?? "",
    ...("shape" in row ? { shape: row.shape, symbol_id: row.symbol_id } : { line_style: row.line_style, directional: row.directional }),
  };
}

/**
 * @param kind Which vocabulary the dialog edits.
 * @param initial The type being edited; omit to create.
 * @param symbols The symbols an element type may use (ignored for a connection type).
 * @param symbolUrl The API path of a symbol's content, for the preview.
 * @param error A save error to show.
 * @param onSave Called with the values for the kind.
 */
export function TypeFormModal({
  kind, initial, symbols = [], symbolUrl = () => "", error, onCancel, onSave,
}: {
  kind: "element" | "connection";
  initial?: ElementType | ConnectionType;
  symbols?: ArchitectureSymbol[];
  symbolUrl?: (symbolId: string) => string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: ElementTypeValues | ConnectionTypeValues) => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => (initial ? draftFrom(initial) : blankDraft()));
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((prev) => ({ ...prev, [key]: value }));
  const noun = kind === "element" ? "element type" : "connection type";

  function save() {
    const common = {
      name: draft.name.trim(), domain: draft.domain,
      color_light: draft.color_light || null, color_dark: draft.color_dark || null,
    };
    onSave(kind === "element"
      ? { ...common, shape: draft.shape, symbol_id: draft.symbol_id }
      : { ...common, line_style: draft.line_style, directional: draft.directional });
  }

  return (
    <Modal title={initial ? `Edit ${initial.name}` : `New ${noun}`} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <FormGridFull>
            <TextField helpNotNeeded required label="Name" value={draft.name} onChange={(value) => set("name", value)} />
          </FormGridFull>
          <LabeledSelect
            help={ARCHITECTURE_HELP.typeDomain} label="Domain" value={draft.domain} placeholder={null}
            onChange={(next) => set("domain", next as Domain)} options={labelOptions(DOMAIN_LABEL)}
          />
          {kind === "element" ? (
            <LabeledSelect
              help={ARCHITECTURE_HELP.typeShape} label="Shape" value={draft.shape} placeholder={null}
              onChange={(next) => set("shape", next as ElementShape)} options={labelOptions(ELEMENT_SHAPE_LABEL)}
            />
          ) : (
            <LabeledSelect
              help={ARCHITECTURE_HELP.connectionLineStyle} label="Line style" value={draft.line_style} placeholder={null}
              onChange={(next) => set("line_style", next as LineStyle)} options={labelOptions(LINE_STYLE_LABEL)}
            />
          )}
          <ColorField
            help={ARCHITECTURE_HELP.typeColor} label="Colour (light theme)" value={draft.color_light}
            onChange={(value) => set("color_light", value)} emptyLabel="Default"
          />
          <ColorField
            help={ARCHITECTURE_HELP.typeColor} label="Colour (dark theme)" value={draft.color_dark}
            onChange={(value) => set("color_dark", value)} emptyLabel="Default"
          />
          {kind === "element" && (
            <FormGridFull>
              <SymbolPicker
                help={ARCHITECTURE_HELP.typeSymbol} label="Symbol" symbols={symbols} value={draft.symbol_id}
                onChange={(next) => set("symbol_id", next)} urlFor={symbolUrl} emptyLabel="Draw the shape"
              />
            </FormGridFull>
          )}
          {kind === "connection" && (
            <FormGridFull>
              <ToggleField
                help={ARCHITECTURE_HELP.connectionDirectional} label="One-way" checked={draft.directional}
                onChange={(next) => set("directional", next)}
              />
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={save} saveDisabled={draft.name.trim() === ""} />
      </div>
    </Modal>
  );
}
