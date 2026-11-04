/**
 * Module: components/ReportLayoutBlockField
 *
 * One field of a block in the outline: picks the control for the field's `kind` (from the block's schema) and
 * shows the server's problems for that field beneath it.
 *
 * Responsibilities:
 * - Draw simple kinds (text, long text, whole and decimal numbers, yes/no, choice, TeX, name, image, a list of lines) with the shared field
 *   components, and composite kinds (source, columns, joins, condition, widget parts, variables) with their own
 *   editors.
 * - Fall back to a JSON box for a kind it does not know, so a module's block type is always editable.
 * - Offer a [+] beside the title of text that allows `{{placeholders}}`, opening a searchable list of what the enclosing blocks name.
 *
 * Design decisions: the field only edits its own key; it never judges the value. An optional key that is
 * emptied is removed from the node, a required one keeps an empty value so the server says it is missing.
 */
import type { BlockCatalogue, BlockField, ReportFieldCatalogue, ReportFontChoice, ReportImageLibrary, ReportWidget } from "../api/reportLayouts";
import type { PackVariableDeclaration } from "../api/reportPacks";
import { useStrings } from "../context/TerminologyContext";
import { useTextSelections } from "../hooks/useTextSelections";
import { newLeaf, sourceRecordType, type NameInScope, type TreeNode } from "../utils/reportLayoutTree";
import {
  DEFAULT_MARGIN_CM, PAGE_ORIENTATIONS, PAGE_SIZES, styleFromTree, styleToTree, type PageMargins, type PageOrientation, type PageSize, type RunningBand, type TableHeadings,
} from "../utils/reportPageSetup";
import type { DocumentStyles } from "../utils/reportFonts";
import { colourNamesUsed, DEFAULT_COLOUR_CONTEXT, type ColourContext, type ColourEntry } from "../utils/reportColours";
import { ColourChoiceField } from "./ColourChoiceField";
import { FileNameField } from "./FileNameField";
import { FontChoiceField } from "./FontChoiceField";
import { ChoiceButtons } from "./ChoiceButtons";
import { FieldHelp } from "./FieldHelp";
import { CheckboxField, TextAreaField, TextField } from "./FormFields";
import { ToggleButton } from "./ToggleButton";
import { ReportImageField } from "./ReportImageField";
import { TextListField } from "./TextListField";
import { LabeledSelect } from "./LabeledSelect";
import { MarkButtons } from "./MarkButtons";
import { ConditionNodeEditor, type Condition, type ConditionEnv } from "./ReportLayoutConditionEditor";
import { ReportColourSchemeEditor } from "./ReportColourSchemeEditor";
import { ReportDocumentStylesField } from "./ReportDocumentStylesField";
import { ReportGridField } from "./ReportGridField";
import { ReportLayoutColumnsEditor, ReportLayoutJoinsEditor } from "./ReportLayoutColumnsEditor";
import { AddPopoverButton } from "./AddPopoverButton";
import { ReportLayoutFieldPicker } from "./ReportLayoutFieldPicker";
import { ReportLayoutJsonField } from "./ReportLayoutJsonField";
import { ReportLayoutSourceEditor } from "./ReportLayoutSourceEditor";
import { ReportLayoutVariablesField } from "./ReportLayoutVariablesField";
import { WidgetKeyField, WidgetParamsField, WidgetSortField } from "./ReportLayoutWidgetEditor";
import { PageMarginsFields } from "./PageMarginsFields";
import { PageStylesEditor } from "./PageStylesEditor";
import { RunningBandEditor } from "./RunningBandEditor";

/** What every field of every block shares. */
export interface BlockEnv {
  blocks: BlockCatalogue;
  catalogue: ReportFieldCatalogue;
  widgets: ReportWidget[];
  /** Names of the layout's declared variables. */
  variables: string[];
  /** Names of the layout's page styles, which a section chooses from. */
  pageStyles: string[];
  /** The layout's sheets and the record type each lists (empty in a document), which a sheet column can link to. */
  sheets?: { name: string; recordType: string | null }[];
  /** The picture library an image block chooses from, and the scope an upload goes to; absent where there is none. */
  images?: { library: ReportImageLibrary; scope: "organization" | "project" };
  /** The branding colour and the organisation's colour scheme, which a colour field offers; stock values where absent. */
  colours?: ColourContext;
  /** The fonts an author may choose; the four standard ones where absent. */
  fonts?: ReportFontChoice[];
  /** The layout's own colour scheme (the root's `palette`). */
  palette?: ColourEntry[];
  /** The layout's default table heading colours (the root's `table_header_fill` and `table_header_text`). */
  tableHeadings?: TableHeadings;
  readOnly: boolean;
}

type Obj = Record<string, unknown>;

/**
 * @param field The field's schema.
 * @param node The block (or the layout) it belongs to.
 * @param names The names the enclosing blocks bring into scope.
 * @param env The catalogues and layout-wide facts.
 * @param problems The server's messages for this field.
 * @param onChange Called with the key and its new value (`undefined` removes the key).
 * @param onChangeMany Called with several keys at once, for an editor that changes more than its own key (the custom table's
 *   editor changes `columns`, `rows` and `header_rows` together); without it the keys are set one after another.
 * @param labelScope Looks a choice's label up under `<scope>.<key>` first, for a field whose choices mean something else here
 *   (an image column's width unit is a share of the column, not of the text).
 */
export function ReportLayoutBlockField({
  field, node, names, env, problems, onChange, onChangeMany, labelScope,
}: {
  field: BlockField;
  node: TreeNode;
  names: NameInScope[];
  env: BlockEnv;
  problems: string[];
  onChange: (key: string, value: unknown) => void;
  onChangeMany?: (patch: Record<string, unknown>) => void;
  labelScope?: string;
}) {
  const strings = useStrings();
  const text = strings.reportOutline;
  const value = node[field.key];
  const help = field.help || undefined;
  const disabled = env.readOnly;
  const set = (next: unknown) => onChange(field.key, next);
  /** An optional text key that is emptied is removed. */
  const setText = (next: string) => set(next === "" && !field.required ? undefined : next);
  const asText = typeof value === "string" ? value : "";
  const hasPlaceholders = field.features.includes("placeholders");
  /** A [+] beside the title of a text field that takes `{{placeholders}}`: it opens the searchable field list and a choice closes it. */
  const insertPlus = hasPlaceholders && !disabled ? (
    <AddPopoverButton label={text.insertFieldInto(field.label)} text={text.insertFieldButton}>
      {(close) => (
        <ReportLayoutFieldPicker
          catalogue={env.catalogue} aliases={names} onInsert={(snippet) => { setText(`${asText}${snippet}`); close(); }}
        />
      )}
    </AddPopoverButton>
  ) : undefined;
  const hasMarks = field.features.includes("marks") || field.features.includes("markdown");
  const selections = useTextSelections<string>();
  /** Bold and Italic beside a text that reads `**` and `*` marks: they wrap the words selected in the field. */
  const markButtons = hasMarks && !disabled ? (
    <MarkButtons
      nameOf={(mark) => text.markField(field.label, mark)}
      onMark={(marker) => selections.mark(field.key, asText, marker, setText)}
    />
  ) : undefined;
  const beside = insertPlus || markButtons ? <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>{insertPlus}{markButtons}</span> : undefined;
  const selectionProps = { onSelect: selections.remember(field.key), onBlur: selections.remember(field.key) };
  /** The layout's own colour scheme: the root's `palette`, which a block's colour field may name. */
  const layoutPalette = (field.kind === "palette" ? (Array.isArray(value) ? value : []) : env.palette ?? []) as ColourEntry[];

  let control;
  switch (field.control === "choice-buttons" && (field.kind === "choice" || field.kind === "integer") ? "choice-buttons"
    : field.control === "toggle" && field.kind === "boolean" ? "toggle" : field.kind) {
    case "choice-buttons": {
      // Choosing the default stores nothing, like clearing the select did, so a block that never set the key stays as it was.
      const isChoice = field.kind === "choice";
      const options: { value: string | number; label: string }[] = isChoice
        ? field.choices.map((c) => ({
          value: c, label: (labelScope ? text.choiceLabels[`${labelScope}.${field.key}`]?.[c] : undefined) ?? text.choiceLabels[field.key]?.[c] ?? c,
        }))
        : Array.from({ length: (field.maximum ?? 0) - (field.minimum ?? 0) + 1 }, (_, i) => {
          const n = (field.minimum ?? 0) + i;
          return { value: n, label: String(n) };
        });
      const current = value === undefined ? field.default : value;
      control = (
        <ChoiceButtons
          label={field.label} value={(typeof current === "string" || typeof current === "number" ? current : "") as string | number}
          options={options} disabled={disabled} help={help} required={field.required}
          onChange={(next) => set(next === field.default && !field.required ? undefined : next)}
        />
      );
      break;
    }
    case "toggle":
      control = (
        <span className="row" style={{ gap: "var(--space-2)", flexWrap: "nowrap" }}>
          <ToggleButton
            label={field.label} iconOnly={false} disabled={disabled} pressed={value === undefined ? field.default === true : value === true}
            onClick={() => {
              const on = !(value === undefined ? field.default === true : value === true);
              set(field.default === true ? (on ? undefined : false) : on ? true : undefined);
            }}
          >
            {field.label}
          </ToggleButton>
          {help && <FieldHelp label={field.label} help={help} />}
        </span>
      );
      break;
    case "text":
    case "tex":
    case "alias":
      control = (
        <TextField
          label={field.label} value={asText} onChange={setText} disabled={disabled} help={help} required={field.required}
          labelExtra={field.kind === "text" ? beside : undefined}
          placeholder={field.kind === "alias" && typeof field.default === "string" ? field.default : undefined}
          inputProps={{ maxLength: field.max_length ?? undefined, spellCheck: field.kind === "tex" ? false : undefined, ...selectionProps }}
        />
      );
      break;
    case "file_name":
      control = (
        <FileNameField
          label={field.label} value={asText} onChange={setText} disabled={disabled} kind="layout" variables={env.variables}
          help={strings.help.reportFileNameLayout}
        />
      );
      break;
    case "longtext":
      control = (
        <TextAreaField
          label={field.label} value={asText} onChange={setText} disabled={disabled} help={help} required={field.required} rows={4}
          labelExtra={beside} inputProps={{ maxLength: field.max_length ?? undefined, ...selectionProps }}
        />
      );
      break;
    case "integer":
      control = (
        <TextField
          label={field.label} value={value === undefined ? "" : String(value)} disabled={disabled} help={help} required={field.required}
          placeholder={field.default !== null && field.default !== undefined ? text.useDefault(String(field.default)) : undefined}
          inputProps={{ type: "number", min: field.minimum ?? undefined, max: field.maximum ?? undefined }}
          onChange={(t) => set(t.trim() === "" ? undefined : Number.isNaN(Number(t)) ? t : Number(t))}
        />
      );
      break;
    case "number":
      control = (
        <TextField
          label={field.label} value={value === undefined ? "" : String(value)} disabled={disabled} help={help} required={field.required}
          placeholder={field.empty_label !== "" ? field.empty_label
            : field.default !== null && field.default !== undefined ? text.useDefault(String(field.default)) : undefined}
          inputProps={{ type: "number", step: "any" }}
          onChange={(t) => set(t.trim() === "" ? undefined : Number.isNaN(Number(t)) ? t : Number(t))}
        />
      );
      break;
    case "image":
      control = env.images ? (
        <ReportImageField
          label={field.label} value={asText} library={env.images.library} scope={env.images.scope} onChange={set}
          disabled={disabled} help={help} required={field.required}
        />
      ) : (
        <ReportLayoutJsonField label={field.label} value={value} onChange={set} help={help} disabled={disabled} required={field.required} />
      );
      break;
    case "text_list":
      control = (
        <TextListField
          label={field.label} value={Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : []}
          onChange={(list) => set(list.length === 0 ? undefined : list)} disabled={disabled} help={help} required={field.required}
          hint={text.onePerLine}
        />
      );
      break;
    case "boolean":
      // A switch that is on unless set off (`default: true`) stores `false` when off and nothing when on; the others store `true` when on.
      control = (
        <CheckboxField
          label={field.label} checked={value === undefined ? field.default === true : value === true} disabled={disabled} help={help}
          onChange={(on) => set(field.default === true ? (on ? undefined : false) : on ? true : undefined)}
        />
      );
      break;
    case "choice":
      control = (
        <LabeledSelect
          label={field.label} value={typeof value === "string" ? value : ""} disabled={disabled} help={help} required={field.required}
          placeholder={
            field.empty_label
            || (field.default !== null && field.default !== undefined ? text.useDefault(String(field.default)) : text.choose)
          }
          options={field.choices.map((c) => ({
            value: c, label: (field.key === "orientation" ? text.orientationLabels[c] : undefined)
              ?? (labelScope ? text.choiceLabels[`${labelScope}.${field.key}`]?.[c] : undefined) ?? text.choiceLabels[field.key]?.[c] ?? c,
          }))}
          onChange={(next) => set(next === "" ? undefined : next)}
        />
      );
      break;
    case "record_field": {
      const type = sourceRecordType(field.depends_on ? node[field.depends_on] : undefined, names);
      const fields = env.catalogue.types.find((t) => t.type === type)?.fields ?? [];
      control = (
        <LabeledSelect
          label={field.label} value={asText} disabled={disabled || type === null} help={help} required={field.required}
          placeholder={text.choose} options={fields.map((f) => ({ value: f.key, label: f.label }))} onChange={setText}
        />
      );
      break;
    }
    case "source":
      control = (
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend><strong>{field.label}</strong></legend>
          <ReportLayoutSourceEditor
            value={(value ?? {}) as Obj} names={names} catalogue={env.catalogue} blocks={env.blocks} variables={env.variables}
            disabled={disabled} onChange={set}
          />
        </fieldset>
      );
      break;
    case "columns": {
      const rootType = sourceRecordType(node.source, names);
      const rootName = typeof node.as === "string" && node.as !== "" ? node.as : "record";
      const joins = Array.isArray(node.joins) ? (node.joins as Obj[]) : [];
      const readable: NameInScope[] = [
        { name: rootName, kind: "record", recordType: rootType },
        ...joins.map((j) => ({
          name: typeof j.as === "string" && j.as !== "" ? j.as : "joined", kind: "record" as const,
          recordType: sourceRecordType(j.source, []),
        })),
      ];
      control = (
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend><strong>{field.label}</strong></legend>
          <ReportLayoutColumnsEditor
            value={(Array.isArray(value) ? value : []) as Obj[]} names={readable} catalogue={env.catalogue} disabled={disabled}
            onChange={(next) => set(next)}
            sheets={node.type === "sheet" ? env.sheets : undefined}
            imageFields={env.blocks.image_column_fields}
            renderImageField={(imageField, rules, recordType, change) => (
              <ReportLayoutBlockField
                key={imageField.key} field={imageField} node={rules} env={env} problems={[]} onChange={change} labelScope="column"
                names={[{ name: "row", kind: "record", recordType }]}
              />
            )}
          />
        </fieldset>
      );
      break;
    }
    case "joins":
      control = (
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend><strong>{field.label}</strong></legend>
          <ReportLayoutJoinsEditor
            value={(Array.isArray(value) ? value : []) as Obj[]} rootName={typeof node.as === "string" && node.as !== "" ? node.as : "record"}
            rootType={sourceRecordType(node.source, names)} catalogue={env.catalogue} blocks={env.blocks} variables={env.variables}
            disabled={disabled} onChange={(next) => set(next.length === 0 ? undefined : next)}
          />
        </fieldset>
      );
      break;
    case "condition": {
      const modules = [...new Map(env.widgets.map((w) => [w.module_key, w.module_name])).entries()].map(([key, name]) => ({ key, name }));
      const conditionEnv: ConditionEnv = { mode: "ref", names, catalogue: env.catalogue, blocks: env.blocks, variables: env.variables, modules, disabled };
      const condition = (value ?? newLeaf("ref")) as Condition;
      control = (
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend><strong>{field.label}</strong></legend>
          <ConditionNodeEditor env={conditionEnv} node={condition} onChange={set} />
          {!disabled && modules.length > 0 && !("module" in condition) && !("all" in condition) && !("any" in condition) && !("not" in condition) && (
            <div>
              <button type="button" className="btn btn-sm" onClick={() => set({ module: "" })}>{text.moduleTest}</button>
            </div>
          )}
        </fieldset>
      );
      break;
    }
    case "widget_key":
      control = <WidgetKeyField widgets={env.widgets} value={asText} disabled={disabled} help={help} onChange={setText} />;
      break;
    case "widget_params":
      control = (
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend><strong>{field.label}</strong></legend>
          <WidgetParamsField
            widget={env.widgets.find((w) => w.key === node.key)} value={(value ?? {}) as Obj} disabled={disabled} onChange={set}
          />
        </fieldset>
      );
      break;
    case "widget_sort":
      control = (
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend><strong>{field.label}</strong></legend>
          <WidgetSortField value={(Array.isArray(value) ? value : []) as { column?: string; descending?: boolean }[]} disabled={disabled} onChange={set} />
        </fieldset>
      );
      break;
    case "variables":
      control = (
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend><strong>{field.label}</strong></legend>
          <ReportLayoutVariablesField
            value={Array.isArray(value) ? (value as PackVariableDeclaration[]) : undefined} catalogue={env.catalogue} disabled={disabled} onChange={set}
          />
        </fieldset>
      );
      break;
    case "colour":
      control = (
        <ColourChoiceField
          label={field.label} value={asText} disabled={disabled} help={help} required={field.required}
          context={env.colours ?? DEFAULT_COLOUR_CONTEXT} layoutPalette={layoutPalette} allowNone={field.key !== "outline" && field.key !== "colour"}
          emptyLabel={field.empty_label || (field.default !== null && field.default !== undefined ? text.useDefault(String(field.default)) : undefined)}
          onChange={setText}
        />
      );
      break;
    case "palette":
      control = (
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend><strong>{field.label}</strong></legend>
          <ReportColourSchemeEditor
            value={layoutPalette} mode="layout" disabled={disabled} context={env.colours ?? DEFAULT_COLOUR_CONTEXT}
            used={colourNamesUsed(node, env.blocks)} onChange={(next) => set(next.length === 0 ? undefined : next)}
          />
        </fieldset>
      );
      break;
    case "font":
      control = (
        <FontChoiceField
          label={field.label} value={asText} fonts={env.fonts} disabled={disabled} help={help} emptyLabel={field.empty_label}
          onChange={(key) => set(key === "" ? undefined : key)}
        />
      );
      break;
    case "document_styles":
      control = (
        <ReportDocumentStylesField
          label={field.label} value={(value ?? undefined) as DocumentStyles | undefined} disabled={disabled} fonts={env.fonts}
          colours={env.colours ?? DEFAULT_COLOUR_CONTEXT} palette={env.palette} onChange={set}
        />
      );
      break;
    case "grid_columns": {
      // One editor changes the table's columns, rows and header count together, so the `rows` field draws nothing of its own.
      const gridText = strings.reportGrid;
      control = (
        <ReportGridField
          label={gridText.fieldLabel} help={gridText.fieldHelp} node={node} disabled={disabled} colours={env.colours} palette={env.palette} tableHeadings={env.tableHeadings} fonts={env.fonts}
          onSave={(patch) => (onChangeMany ? onChangeMany({ ...patch }) : Object.entries(patch).forEach(([key, v]) => onChange(key, v)))}
          renderCellText={(cell, onText, label) => (
            <ReportLayoutBlockField
              field={{
                key: "text", label, kind: "longtext", required: false, help: gridText.cellTextHelp, max_length: 2000, minimum: null, maximum: null,
                default: null, choices: [], features: ["placeholders", "math", "markdown"], depends_on: null, families: [], empty_label: "",
                group: "", basic: false, control: "", inline: false,
              }}
              node={cell} names={names} env={env} problems={[]} onChange={(_, next) => onText(typeof next === "string" ? next : "")}
            />
          )}
        />
      );
      break;
    }
    case "grid_rows":
      control = null;
      break;
    case "page_style": {
      const unknown = asText !== "" && !env.pageStyles.includes(asText);
      control = (
        <LabeledSelect
          label={field.label} value={asText} disabled={disabled} help={help} required={field.required}
          placeholder={env.pageStyles.length === 0 ? strings.pageSetup.noStylesToChoose : strings.pageSetup.chooseStyle}
          options={[
            ...env.pageStyles.map((name) => ({ value: name, label: name })),
            ...(unknown ? [{ value: asText, label: strings.pageSetup.unknownStyle(asText) }] : []),
          ]}
          onChange={setText}
        />
      );
      break;
    }
    case "margins":
      control = (
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend><strong>{field.label}</strong></legend>
          <PageMarginsFields
            value={(value ?? {}) as PageMargins} mirror={node.mirror_margins === true} disabled={disabled}
            onChange={(next) => set(Object.keys(next).length === 0 ? undefined : next)}
          />
        </fieldset>
      );
      break;
    case "page_styles": {
      const entries = (Array.isArray(value) ? value : []) as Record<string, unknown>[];
      const size = PAGE_SIZES.includes(node.page_size as PageSize) ? (node.page_size as PageSize) : "A4";
      const orientation = PAGE_ORIENTATIONS.includes(node.orientation as PageOrientation) ? (node.orientation as PageOrientation) : "portrait";
      control = (
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend><strong>{field.label}</strong></legend>
          <PageStylesEditor
            value={entries.map(styleFromTree)} disabled={disabled} images={env.images} placeholders={env.catalogue.placeholders}
            look={{ fonts: env.fonts, colours: env.colours, palette: env.palette }}
            base={{ size, orientation, margins: (node.margins ?? {}) as PageMargins, mirror: node.mirror_margins === true }}
            onChange={(next) => set(next.length === 0 ? undefined : next.map(styleToTree))}
          />
        </fieldset>
      );
      break;
    }
    case "running_band": {
      const margins = (node.margins ?? {}) as PageMargins;
      control = (
        <RunningBandEditor
          kind={field.key === "footer" ? "footer" : "header"} value={value as RunningBand | undefined} onChange={set} inheritFrom="template"
          margin={(field.key === "footer" ? margins.bottom : margins.top) ?? DEFAULT_MARGIN_CM} images={env.images}
          placeholders={env.catalogue.placeholders} look={{ fonts: env.fonts, colours: env.colours, palette: env.palette }} disabled={disabled}
        />
      );
      break;
    }
    default:
      control = <ReportLayoutJsonField label={field.label} value={value} onChange={set} help={help} disabled={disabled} required={field.required} />;
  }

  return (
    <div className="stack" style={{ gap: "var(--space-1)" }} data-field={field.key}>
      {control}
      {problems.length > 0 && (
        <ul className="outline-field-problems" role="alert">
          {problems.map((message, i) => <li key={i}>{message}</li>)}
        </ul>
      )}
    </div>
  );
}
