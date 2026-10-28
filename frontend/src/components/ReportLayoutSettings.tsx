/**
 * Module: components/ReportLayoutSettings
 *
 * The layout-level part of the designer's block views: problems about the layout itself and a "Layout settings"
 * section holding the keys that belong to the layout rather than to a block (page orientation, variables).
 *
 * Responsibilities: draw the layout fields the block catalogue lists for the layout's family with the shared field
 * forms, list the server's problems that are not about any block (and not already shown on a settings field), and
 * open the section on its own when one of its fields has a problem.
 */
import type { BlockCatalogue, LayoutFamily, TreeProblem } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { owningNode, setAt, type Tree } from "../utils/reportLayoutTree";
import { ReportLayoutOutlineField, type OutlineEnv } from "./ReportLayoutOutlineField";

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
  env: OutlineEnv;
  problems: TreeProblem[];
}) {
  const text = useStrings().reportOutline;
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
      {fields.length > 0 && (
        <details className="card stack" open={fields.some((f) => layoutProblems.some((p) => aboutField(p, f.key)))}>
          <summary><strong>{text.settingsTitle}</strong></summary>
          <div className="stack" style={{ marginTop: "var(--space-3)" }}>
            {fields.map((field) => (
              <ReportLayoutOutlineField
                key={field.key} field={field} node={tree} names={[]} env={env}
                problems={layoutProblems.filter((p) => aboutField(p, field.key)).map((p) => p.message)}
                onChange={(key, value) => onChange(setAt(tree, [key], value))}
              />
            ))}
          </div>
        </details>
      )}
    </>
  );
}
