/**
 * Module: components/ReportLayoutSettings
 *
 * The layout-level part of the block editor: the keys that belong to the layout rather than to a block (page
 * orientation, variables), shown in the block editor beside the canvas when the layout block is selected.
 *
 * Responsibilities: draw the layout fields the block catalogue lists for the layout's family with the shared field
 * forms, and list the server's problems that are not about any block (and not already shown on a settings field).
 */
import type { BlockCatalogue, LayoutFamily, TreeProblem } from "../api/reportLayouts";
import { owningNode, setAt, type Tree } from "../utils/reportLayoutTree";
import { ReportLayoutBlockField, type BlockEnv } from "./ReportLayoutBlockField";

/**
 * @param tree The layout tree.
 * @param onChange Called with the edited tree.
 * @param family The layout's family; only fields for it are drawn.
 * @param blocks The block catalogue (its layout fields).
 * @param env The catalogues and layout-wide facts the field forms need.
 * @param problems The server's problems for the whole tree.
 */
export function ReportLayoutSettings({
  tree, onChange, family, blocks, env, problems,
}: {
  tree: Tree;
  onChange: (next: Tree) => void;
  family: LayoutFamily;
  blocks: BlockCatalogue;
  env: BlockEnv;
  problems: TreeProblem[];
}) {
  const layoutProblems = problems.filter((p) => owningNode(p.path) === null);
  const fields = blocks.layout_fields.filter((f) => f.families.length === 0 || f.families.includes(family));
  const aboutField = (p: TreeProblem, key: string) => p.path === key || p.path.startsWith(`${key}[`) || p.path.startsWith(`${key}.`);
  const loose = layoutProblems.filter((p) => !fields.some((f) => aboutField(p, f.key)));
  return (
    <>
      {loose.length > 0 && (
        <ul className="outline-field-problems" role="alert">
          {loose.map((p, i) => <li key={i}>{p.path === "" ? p.message : `${p.path}: ${p.message}`}</li>)}
        </ul>
      )}
      {fields.map((field) => (
        <ReportLayoutBlockField
          key={field.key} field={field} node={tree} names={[]} env={env}
          problems={layoutProblems.filter((p) => aboutField(p, field.key)).map((p) => p.message)}
          onChange={(key, value) => onChange(setAt(tree, [key], value))}
        />
      ))}
    </>
  );
}
