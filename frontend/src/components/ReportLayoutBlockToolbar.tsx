/**
 * Module: components/ReportLayoutBlockToolbar
 *
 * The row of icon buttons above the text view that insert a block's starter text (a heading of a level, text, a
 * repeated section, a table, an if, an equation, a page break, a sheet) at the caret.
 *
 * Responsibilities: one icon button per block that suits the layout's family, each with a tooltip (`Tooltip`) naming
 * the block and the accessible name "Insert block: <name>"; call `onInsert` with the block's starter text. Which
 * blocks exist and what they insert is `BLOCK_SNIPPETS`; this component only draws them.
 *
 * Design decisions: icons rather than words so the row stays one line however many blocks there are; the tooltip and
 * the accessible name keep every button identifiable (style guide, "Pattern: icon buttons").
 */
import {
  FileSpreadsheet, GitBranch, Heading1, Heading2, Heading3, Layers, RectangleHorizontal, Repeat, Sigma, SeparatorHorizontal, Table, Type,
  type LucideIcon,
} from "lucide-react";

import type { LayoutFamily } from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { BLOCK_SNIPPETS } from "../utils/reportLayoutText";
import { Tooltip } from "./Tooltip";

/** The icon of each block. A block with no entry here cannot be drawn, so the list fails the type check. */
const BLOCK_ICONS: Record<string, LucideIcon> = {
  heading_1: Heading1,
  heading_2: Heading2,
  heading_3: Heading3,
  text: Type,
  each: Repeat,
  group: Layers,
  table: Table,
  if: GitBranch,
  equation: Sigma,
  page_break: SeparatorHorizontal,
  section: RectangleHorizontal,
  sheet: FileSpreadsheet,
};

/**
 * @param family The layout's family; only blocks that suit it are offered.
 * @param onInsert Called with the block's starter text to put on lines of their own at the caret.
 */
export function ReportLayoutBlockToolbar({ family, onInsert }: { family: LayoutFamily; onInsert: (text: string) => void }) {
  const text = useStrings().reportLayouts;
  return (
    <div className="row" role="toolbar" aria-label={text.insertBlock} style={{ flexWrap: "wrap", gap: "var(--space-1)" }}>
      {BLOCK_SNIPPETS.filter((block) => block.families.includes(family)).map((block) => {
        const Icon = BLOCK_ICONS[block.key];
        const name = text.blockLabels[block.key];
        return (
          <Tooltip key={block.key} label={name}>
            <button
              type="button" className="btn btn-sm btn-icon" aria-label={`${text.insertBlock}: ${name}`}
              onClick={() => onInsert(block.text)}
            >
              <Icon aria-hidden="true" />
            </button>
          </Tooltip>
        );
      })}
    </div>
  );
}
