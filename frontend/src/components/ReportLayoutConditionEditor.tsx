/**
 * Module: components/ReportLayoutConditionEditor
 *
 * Edits a layout condition: a single test, or `all of` / `any of` / `not` groups of tests nested up to a few
 * levels. Used for a source's `where` list (tests on a field of the records) and for an `if` block's `when`
 * (a test on a field of an enclosing record, or "a module is available").
 *
 * Responsibilities:
 * - Offer the operators the server accepts for the chosen field's kind (from the block catalogue), and a value
 *   control that suits the kind: a choice list for an enum, a number, a date, yes/no, or text; several values
 *   as comma-separated text (a choice list for an enum).
 * - Show a `{var: name}` value as "uses variable x", switchable to a plain value, and offer a variable when the
 *   layout declares one.
 *
 * Design decisions: the editor builds the same JSON the server validates and applies no rule of its own beyond
 * offering the operators it was given; an operator or value the author leaves unfinished is reported by the
 * server's `validate`, shown beside the block.
 */
import type { BlockCatalogue, ReportFieldCatalogue, ReportFieldInfo } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { newLeaf, type NameInScope } from "../utils/reportLayoutTree";
import { CommaListField } from "./CommaListField";
import { TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { MultiSelectDropdown } from "./MultiSelectDropdown";

/** A condition node as stored: a leaf, or one of `all` / `any` / `not`. */
export type Condition = Record<string, unknown>;

/** Deepest the editor lets groups nest (the server allows four levels). */
const MAX_NESTING = 3;

/** What the editor needs to know about where a condition sits. */
export interface ConditionEnv {
  /** `record`: a leaf is `{field, op, value}` over `recordType`. `ref`: a leaf is `{ref: "name.field", ...}` or `{module}`. */
  mode: "record" | "ref";
  recordType?: string | null;
  names?: NameInScope[];
  catalogue: ReportFieldCatalogue;
  blocks: BlockCatalogue;
  /** Names of the layout's declared variables. */
  variables: string[];
  /** Modules offered by "a module is available" (ref mode). */
  modules: { key: string; name: string }[];
  disabled?: boolean;
}

/** A field of a name in scope (`req.status`): from the record type, or the group's value/count. */
function fieldOf(env: ConditionEnv, name: string, key: string): ReportFieldInfo | null {
  const scoped = env.names?.find((n) => n.name === name);
  if (!scoped) return null;
  if (scoped.kind === "group") {
    const kind = env.catalogue.group_fields[key];
    return kind ? { key, label: key === "value" ? "Value" : "Count", kind, reserved: true, choices: [] } : null;
  }
  return env.catalogue.types.find((t) => t.type === scoped.recordType)?.fields.find((f) => f.key === key) ?? null;
}

function leafField(env: ConditionEnv, leaf: Condition): ReportFieldInfo | null {
  if (env.mode === "record") return env.catalogue.types.find((t) => t.type === env.recordType)?.fields.find((f) => f.key === leaf.field) ?? null;
  const [name, key] = typeof leaf.ref === "string" ? leaf.ref.split(".") : [];
  return name && key ? fieldOf(env, name, key) : null;
}

const isReference = (value: unknown): value is { var: string } =>
  value !== null && typeof value === "object" && typeof (value as { var?: unknown }).var === "string";

/** The text of a value for a plain input. */
const asText = (value: unknown): string => (Array.isArray(value) ? value.join(", ") : value === undefined || value === null ? "" : String(value));

/** Reads typed text into the value a field of this kind stores. */
function fromText(kind: string, text: string): unknown {
  if (kind === "number") return text.trim() === "" || Number.isNaN(Number(text)) ? text : Number(text);
  return text;
}

function ValueControl({
  env, leaf, field, onChange,
}: { env: ConditionEnv; leaf: Condition; field: ReportFieldInfo | null; onChange: (value: unknown) => void }) {
  const text = useStrings().reportOutline;
  const many = env.blocks.list_operators.includes(String(leaf.op ?? ""));
  const kind = field?.kind ?? "text";
  const value = leaf.value;

  if (isReference(value)) {
    return (
      <span className="row" style={{ gap: "var(--space-2)" }}>
        <span className="text-muted">{text.variableValue(value.var)}</span>
        <button type="button" className="btn btn-sm" disabled={env.disabled} onClick={() => onChange("")}>{text.useValue}</button>
      </span>
    );
  }
  const variablePicker = env.variables.length > 0 && !env.disabled && (
    <LabeledSelect helpNotNeeded
      label={text.variablePick} value="" placeholder={text.useVariable}
      options={env.variables.map((v) => ({ value: v, label: v }))}
      onChange={(name) => { if (name !== "") onChange({ var: name }); }}
    />
  );

  let control;
  if (kind === "enum" && field && field.choices.length > 0 && many) {
    const chosen = new Set(Array.isArray(value) ? value.map(String) : []);
    control = (
      <MultiSelectDropdown
        triggerLabel={text.conditionValues} emptyLabel={text.choose} summaryLimit={3}
        options={field.choices.map((c) => ({
          value: c, label: c, checked: chosen.has(c), optionLabel: c,
          onToggle: () => {
            const next = new Set(chosen);
            if (chosen.has(c)) next.delete(c);
            else next.add(c);
            onChange([...next]);
          },
        }))}
      />
    );
  } else if (kind === "enum" && field && field.choices.length > 0) {
    control = (
      <LabeledSelect helpNotNeeded
        label={text.conditionValue} value={asText(value)} placeholder={text.choose} disabled={env.disabled}
        options={field.choices.map((c) => ({ value: c, label: c }))} onChange={onChange}
      />
    );
  } else if (kind === "bool") {
    control = (
      <LabeledSelect helpNotNeeded
        label={text.conditionValue} value={value === true ? "true" : value === false ? "false" : ""} placeholder={text.choose}
        disabled={env.disabled} options={[{ value: "true", label: text.yes }, { value: "false", label: text.no }]}
        onChange={(v) => onChange(v === "" ? undefined : v === "true")}
      />
    );
  } else if (many) {
    control = (
      <CommaListField
        label={text.conditionValues} value={Array.isArray(value) ? value : []} disabled={env.disabled}
        parse={(part) => fromText(kind, part)} onChange={onChange}
      />
    );
  } else {
    control = (
      <TextField helpNotNeeded
        label={text.conditionValue} value={asText(value)} disabled={env.disabled}
        inputProps={{ type: kind === "number" ? "number" : kind === "date" ? "date" : "text" }}
        onChange={(t) => onChange(fromText(kind, t))}
      />
    );
  }
  return <span className="row" style={{ gap: "var(--space-2)", alignItems: "flex-end" }}>{control}{variablePicker}</span>;
}

function Leaf({ env, node, onChange }: { env: ConditionEnv; node: Condition; onChange: (next: Condition) => void }) {
  const text = useStrings().reportOutline;
  const recordTypeFields = env.catalogue.types.find((t) => t.type === env.recordType)?.fields ?? [];
  const names = env.names ?? [];
  const [refName = "", refKey = ""] = typeof node.ref === "string" ? node.ref.split(".") : [];
  const scoped = names.find((n) => n.name === refName);
  const field = leafField(env, node);
  const operators = env.blocks.operators[field?.kind ?? "text"] ?? [];

  function change(patch: Condition) {
    const next: Condition = { ...node, ...patch };
    // A test that takes no value drops a stale one.
    if (env.blocks.valueless_operators.includes(String(next.op))) delete next.value;
    onChange(next);
  }

  if (env.mode === "ref" && "module" in node) {
    return (
      <LabeledSelect helpNotNeeded
        label={text.moduleKey} value={String(node.module ?? "")} placeholder={text.choose} disabled={env.disabled}
        options={env.modules.map((m) => ({ value: m.key, label: m.name }))} onChange={(module) => onChange({ module })}
      />
    );
  }
  const refFields = scoped?.kind === "group"
    ? Object.keys(env.catalogue.group_fields).map((k) => ({ value: k, label: k }))
    : (env.catalogue.types.find((t) => t.type === scoped?.recordType)?.fields ?? []).map((f) => ({ value: f.key, label: f.label }));
  return (
    <span className="row" style={{ gap: "var(--space-2)", alignItems: "flex-end", flexWrap: "wrap" }}>
      {env.mode === "record" ? (
        <LabeledSelect helpNotNeeded
          label={text.conditionField} value={String(node.field ?? "")} placeholder={text.choose} disabled={env.disabled}
          options={recordTypeFields.map((f) => ({ value: f.key, label: f.label }))}
          onChange={(key) => onChange({ field: key, op: "eq", value: "" })}
        />
      ) : (
        <>
          <LabeledSelect helpNotNeeded
            label={text.conditionName} value={refName} placeholder={text.choose} disabled={env.disabled}
            options={names.map((n) => ({ value: n.name, label: n.name }))}
            onChange={(name) => onChange({ ref: `${name}.`, op: "eq", value: "" })}
          />
          <LabeledSelect helpNotNeeded
            label={text.conditionField} value={refKey} placeholder={text.choose} disabled={env.disabled || !refName}
            options={refFields} onChange={(key) => onChange({ ref: `${refName}.${key}`, op: "eq", value: "" })}
          />
        </>
      )}
      <LabeledSelect helpNotNeeded
        label={text.conditionOp} value={String(node.op ?? "")} placeholder={text.choose} disabled={env.disabled || !field}
        options={operators.map((o) => ({ value: o, label: text.operatorLabels[o] ?? o }))} onChange={(op) => change({ op })}
      />
      {field && node.op !== undefined && !env.blocks.valueless_operators.includes(String(node.op)) && (
        <ValueControl env={env} leaf={node} field={field} onChange={(value) => change({ value })} />
      )}
    </span>
  );
}

type Kind = "test" | "all" | "any" | "not";
const kindOf = (node: Condition): Kind => (["all", "any", "not"] as const).find((k) => k in node) ?? "test";

/**
 * One condition node (recursive).
 *
 * @param env Where the condition sits and what it may name.
 * @param node The condition.
 * @param onChange Called with the edited condition.
 * @param onRemove Removes this node from its parent (omitted for the root of a single condition).
 * @param depth How deeply groups are nested so far.
 */
export function ConditionNodeEditor({
  env, node, onChange, onRemove, depth = 1,
}: { env: ConditionEnv; node: Condition; onChange: (next: Condition) => void; onRemove?: () => void; depth?: number }) {
  const text = useStrings().reportOutline;
  const kind = kindOf(node);
  const kinds: Kind[] = depth >= MAX_NESTING ? ["test"] : ["test", "all", "any", "not"];
  const children: Condition[] = kind === "not" ? (node.not ? [node.not as Condition] : []) : ((node[kind] as Condition[] | undefined) ?? []);

  function setKind(next: string) {
    if (next === kind) return;
    if (next === "test") onChange(newLeaf(env.mode));
    else if (next === "not") onChange({ not: kind === "test" ? node : (children[0] ?? newLeaf(env.mode)) });
    else onChange({ [next]: kind === "test" ? [node, newLeaf(env.mode)] : [...children, ...(children.length < 2 ? [newLeaf(env.mode)] : [])] });
  }

  function setChild(i: number, child: Condition) {
    if (kind === "not") onChange({ not: child });
    else onChange({ [kind]: children.map((c, j) => (j === i ? child : c)) });
  }

  return (
    <div className="stack" style={{ gap: "var(--space-2)" }} role="group" aria-label={text.conditionKinds[kind]}>
      <span className="row" style={{ gap: "var(--space-2)", alignItems: "flex-end", flexWrap: "wrap" }}>
        {kinds.length > 1 && (
          <LabeledSelect helpNotNeeded
            label={text.conditionKind} value={kind} placeholder={null} disabled={env.disabled}
            options={kinds.map((k) => ({ value: k, label: text.conditionKinds[k] }))} onChange={setKind}
          />
        )}
        {kind === "test" && <Leaf env={env} node={node} onChange={onChange} />}
        {onRemove && !env.disabled && (
          <button type="button" className="btn btn-sm" onClick={onRemove}>{text.removeCondition}</button>
        )}
      </span>
      {kind !== "test" && (
        <div className="stack" style={{ paddingLeft: "var(--space-4)", gap: "var(--space-2)" }}>
          {children.map((child, i) => (
            <ConditionNodeEditor
              key={i} env={env} node={child} depth={depth + 1} onChange={(next) => setChild(i, next)}
              onRemove={kind === "not" ? undefined : () => onChange({ [kind]: children.filter((_, j) => j !== i) })}
            />
          ))}
          {kind !== "not" && !env.disabled && (
            <div>
              <button type="button" className="btn btn-sm" onClick={() => onChange({ [kind]: [...children, newLeaf(env.mode)] })}>
                {text.addCondition}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * A `where` list: every entry must hold (an implicit "all").
 *
 * @param env Where the list sits (record mode).
 * @param value The entries.
 * @param onChange Called with the new list (empty when the last entry is removed).
 */
export function ConditionListEditor({ env, value, onChange }: { env: ConditionEnv; value: Condition[]; onChange: (next: Condition[]) => void }) {
  const text = useStrings().reportOutline;
  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      {value.map((node, i) => (
        <ConditionNodeEditor
          key={i} env={env} node={node} onChange={(next) => onChange(value.map((c, j) => (j === i ? next : c)))}
          onRemove={() => onChange(value.filter((_, j) => j !== i))}
        />
      ))}
      {!env.disabled && (
        <div className="row" style={{ gap: "var(--space-2)" }}>
          <button type="button" className="btn btn-sm" onClick={() => onChange([...value, newLeaf("record")])}>{text.addCondition}</button>
          <button type="button" className="btn btn-sm" onClick={() => onChange([...value, { all: [newLeaf("record"), newLeaf("record")] }])}>
            {text.addGroup}
          </button>
        </div>
      )}
    </div>
  );
}
