/**
 * Module: components/ReportLayoutSettings
 *
 * The layout-level part of the block editor: the keys that belong to the layout rather than to a block (page
 * orientation, variables), shown in the block editor beside the canvas when the layout block is selected.
 *
 * Responsibilities: draw the layout fields the block catalogue lists for the layout's family with the shared field
 * forms, arranged in the shared setting groups (`LayoutSettingGroup`: all collapsible, remembered per person and marked
 * when they hold a non-default value; Page and Margins say their effective value on the bar), and list the server's problems that are not about any block (and not already shown on a settings field).
 * An organisation layout that prints a project's name or code without being limited to one project gets a hint to
 * set "Projects it runs for" (a hint only, never an automatic change).
 */
import type { BlockCatalogue, LayoutFamily, TreeProblem } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { groupLayoutFields, marginsGroupSummary, pageGroupSummary, treeSettingChanges, type LayoutSettingGroupKey } from "../utils/reportLayoutSettingGroups";
import { owningNode, setAt, type Tree } from "../utils/reportLayoutTree";
import { PAGE_ORIENTATIONS, PAGE_SIZES, type PageMargins, type PageOrientation, type PageSize, type TableHeadings } from "../utils/reportPageSetup";
import { LayoutSettingGroup } from "./LayoutSettingGroup";
import { ReportLayoutBlockField, type BlockEnv } from "./ReportLayoutBlockField";
import { TableHeadingColours } from "./TableHeadingColours";

/** The two root keys the one table-heading control sets together. */
const HEADING_KEYS = ["table_header_fill", "table_header_text"] as const;

/** A stored colour word, or `undefined` for an unset or non-text value. */
const asWord = (value: unknown): string | undefined => (typeof value === "string" && value !== "" ? value : undefined);

/** A placeholder that prints the project a report ran for, which has no single answer in an organisation-wide run. */
const PROJECT_PLACEHOLDER = /\{\{\s*project_(name|code|description)\s*\}\}/;

/**
 * @param tree The layout tree.
 * @param onChange Called with the edited tree.
 * @param family The layout's family; only fields for it are drawn.
 * @param blocks The block catalogue (its layout fields).
 * @param env The catalogues and layout-wide facts the field forms need.
 * @param problems The server's problems for the whole tree.
 * @param newLayout Whether the layout is new (Page and Margins then start open).
 */
export function ReportLayoutSettings({
  tree, onChange, family, blocks, env, problems, newLayout = false,
}: {
  tree: Tree;
  onChange: (next: Tree) => void;
  family: LayoutFamily;
  blocks: BlockCatalogue;
  env: BlockEnv;
  problems: TreeProblem[];
  newLayout?: boolean;
}) {
  const strings = useStrings();
  const labels = strings.pageSetup;
  const suggestSingleProject =
    env.images?.scope === "organization" && (tree.run_scope ?? "any") === "any" && PROJECT_PLACEHOLDER.test(JSON.stringify(tree));
  const layoutProblems = problems.filter((p) => owningNode(p.path) === null);
  const fields = blocks.layout_fields.filter((f) => f.families.length === 0 || f.families.includes(family));
  const aboutField = (p: TreeProblem, key: string) => p.path === key || p.path.startsWith(`${key}[`) || p.path.startsWith(`${key}.`);
  const loose = layoutProblems.filter((p) => !fields.some((f) => aboutField(p, f.key)));
  const changes = treeSettingChanges(tree, fields);
  const size: PageSize = PAGE_SIZES.includes(tree.page_size as PageSize) ? (tree.page_size as PageSize) : "A4";
  const orientation: PageOrientation = PAGE_ORIENTATIONS.includes(tree.orientation as PageOrientation) ? (tree.orientation as PageOrientation) : "portrait";
  /** The bar text of the two groups that always have a value. */
  const summaries: Partial<Record<LayoutSettingGroupKey, string>> = {
    page: pageGroupSummary(size, orientation, tree.mirror_margins === true, {
      orientation: (o) => labels.orientationLabels[o].toLowerCase(), mirrored: labels.pageSummaryMirrored,
    }),
    margins: marginsGroupSummary((tree.margins ?? {}) as PageMargins, { all: labels.marginsSummaryAll, sides: labels.marginsSummarySides }),
  };
  return (
    <>
      {loose.length > 0 && (
        <ul className="outline-field-problems" role="alert">
          {loose.map((p, i) => <li key={i}>{p.path === "" ? p.message : `${p.path}: ${p.message}`}</li>)}
        </ul>
      )}
      {suggestSingleProject && <p role="note" className="text-muted">{strings.reportLayouts.singleProjectHint}</p>}
      {groupLayoutFields(fields).map((group) => (
        <LayoutSettingGroup
          key={group.key} group={group.key} changed={changes[group.key]} summary={summaries[group.key]} newLayout={newLayout}
          problems={group.fields.reduce((n, f) => n + layoutProblems.filter((p) => aboutField(p, f.key)).length, 0)}
        >
          {group.fields.map((field) => field.key === HEADING_KEYS[1] ? null : field.key === HEADING_KEYS[0] ? (
            <TableHeadingColours
              key={field.key} colours={env.colours} palette={env.palette} disabled={env.readOnly}
              value={{ fill: asWord(tree[HEADING_KEYS[0]]), text: asWord(tree[HEADING_KEYS[1]]) }}
              problems={HEADING_KEYS.flatMap((key) => layoutProblems.filter((p) => aboutField(p, key)).map((p) => p.message))}
              onChange={(next: TableHeadings) => onChange(setAt(setAt(tree, [HEADING_KEYS[0]], next.fill), [HEADING_KEYS[1]], next.text))}
            />
          ) : (
            <ReportLayoutBlockField
              key={field.key} field={field} node={tree} names={[]} env={env}
              problems={layoutProblems.filter((p) => aboutField(p, field.key)).map((p) => p.message)}
              onChange={(key, value) => onChange(setAt(tree, [key], value))}
            />
          ))}
        </LayoutSettingGroup>
      ))}
    </>
  );
}
