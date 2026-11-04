/**
 * Module: components/ReportLayoutBlockForm
 *
 * The form of one selected block in the Blocks view: its basic fields, then the collapsible groups its schema declares.
 *
 * Responsibilities:
 * - Draw every field of the block type through `ReportLayoutBlockField`, in the arrangement `arrangeBlockFields`
 *   reads from the schema (a type with no groups is flat).
 * - Draw each group through the shared `SettingGroup`: closed unless the schema opens it, remembered per person and per
 *   block type, with an "N changed" pill and accent edge when a hidden setting is not at its default, and held open
 *   with a danger pill when the server reported a problem inside it.
 *
 * Design decisions: arrangement only. A field marked `inline` shares a row with the field before it (a value and its
 * unit), stacking when the panel is too narrow. A group's fields are the same controls, with the same names, as in a flat form,
 * so a block of a module is arranged by its own schema with no edit here.
 */
import type { BlockType } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { arrangeBlockFields, blockGroupKey } from "../utils/reportBlockForm";
import { settingIsSet } from "../utils/reportLayoutSettingGroups";
import type { NameInScope, TreeNode } from "../utils/reportLayoutTree";
import { ReportLayoutBlockField, type BlockEnv } from "./ReportLayoutBlockField";
import { SettingGroup } from "./SettingGroup";

/**
 * @param type The block type (its fields and groups).
 * @param node The block being edited.
 * @param names The names the enclosing blocks bring into scope.
 * @param env The catalogues and layout-wide facts.
 * @param problemsByKey The server's messages, by the field key they are about.
 * @param onChange Called with a key and its new value (`undefined` removes it).
 * @param onChangeMany Called with several keys at once.
 */
export function ReportLayoutBlockForm({
  type, node, names, env, problemsByKey, onChange, onChangeMany,
}: {
  type: BlockType;
  node: TreeNode;
  names: NameInScope[];
  env: BlockEnv;
  problemsByKey: Map<string, string[]>;
  onChange: (key: string, value: unknown) => void;
  onChangeMany: (patch: Record<string, unknown>) => void;
}) {
  const text = useStrings().reportOutline;
  const arranged = arrangeBlockFields(type, text.otherGroup);
  const draw = (field: (typeof type.fields)[number]) => (
    <ReportLayoutBlockField
      key={field.key} field={field} node={node} names={names} env={env} problems={problemsByKey.get(field.key) ?? []}
      onChange={onChange} onChangeMany={onChangeMany}
    />
  );
  /** Draws fields in order, putting each `inline` field on one row with the field before it (a value and its unit). */
  const drawAll = (fields: typeof type.fields) => {
    const rows: (typeof type.fields)[] = [];
    for (const f of fields) {
      if (f.inline && rows.length > 0) rows[rows.length - 1].push(f);
      else rows.push([f]);
    }
    return rows.map((row) => row.length === 1 ? draw(row[0]) : (
      <div key={row[0].key} className="block-field-row">{row.map(draw)}</div>
    ));
  };
  return (
    <>
      {drawAll(arranged.basic)}
      {arranged.groups.map(({ group, fields }) => (
        <SettingGroup
          key={group.key} sectionKey={blockGroupKey(type.type, group.key)} title={group.label} defaultOpen={group.open}
          changed={fields.filter((f) => settingIsSet(f, node[f.key])).length}
          problems={fields.reduce((n, f) => n + (problemsByKey.get(f.key)?.length ?? 0), 0)}
        >
          {drawAll(fields)}
        </SettingGroup>
      ))}
    </>
  );
}
