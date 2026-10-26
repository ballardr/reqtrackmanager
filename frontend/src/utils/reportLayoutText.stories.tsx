import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import type { ReportWidget } from "../api/reportLayouts";
import { buildWidgets } from "../testing/reportLayoutFixtures";
import {
  aliasesInScope, asBlock, diffLines, insertAt, insertionRange, lineOfOffset, offsetOfLine, placeholder, widgetLine,
} from "./reportLayoutText";

/** The pure helpers behind the layout designer's editor, exercised as plain functions (the stories render nothing). */
const meta: Meta = { title: "Utils/reportLayoutText", render: () => <p>Pure helpers; see the interactions.</p> };
export default meta;

type Story = StoryObj;

export const AliasesComeFromTheOpenBlocksOnly: Story = {
  play: async () => {
    const text = "@group requirement by status as grp\n  @each in grp as req\n    x\n  @end\n  y\n@end\nz\n";
    await expect(aliasesInScope(text, 2)).toEqual([
      { name: "grp", kind: "group", recordType: "requirement" },
      { name: "req", kind: "record", recordType: "requirement" },
    ]);
    // After the inner @end only the group is open; after the last @end nothing is.
    await expect(aliasesInScope(text, 4).map((a) => a.name)).toEqual(["grp"]);
    await expect(aliasesInScope(text, 6)).toEqual([]);
  },
};

export const DefaultAliasesApplyWhenNoneIsWritten: Story = {
  play: async () => {
    await expect(aliasesInScope("@each requirement\n\n@end\n", 1).map((a) => a.name)).toEqual(["record"]);
    await expect(aliasesInScope("@group requirement by status\n\n@end\n", 1).map((a) => a.name)).toEqual(["group"]);
  },
};

export const OtherBlocksAndTextBlocksAreSkippedOver: Story = {
  play: async () => {
    const text = "@if x eq 1\n  @each decision as d\n  @text\n@each requirement as fake\n@end\n  here\n";
    // The @if opens a block without a name; @text ... @end is prose, so `fake` never opens; `d` is still open.
    await expect(aliasesInScope(text, 6).map((a) => a.name)).toEqual(["d"]);
  },
};

export const LinesAndOffsetsAgree: Story = {
  play: async () => {
    const text = "one\ntwo\nthree";
    await expect(lineOfOffset(text, 0)).toBe(0);
    await expect(lineOfOffset(text, 4)).toBe(1);
    await expect(lineOfOffset(text, text.length)).toBe(2);
    await expect(offsetOfLine(text, 1)).toBe(0);
    await expect(offsetOfLine(text, 3)).toBe(8);
    await expect(offsetOfLine(text, 9)).toBe(text.length);
  },
};

export const InsertingReplacesTheSelectionAndMovesTheCaret: Story = {
  play: async () => {
    await expect(insertAt("abcdef", 2, 4, "XY")).toEqual({ text: "abXYef", caret: 4 });
    await expect(insertAt("", 0, 0, "x")).toEqual({ text: "x", caret: 1 });
  },
};

export const AnInsertionNeverGoesBeforeOrOnTheLayoutLine: Story = {
  play: async () => {
    const text = "@layout document portrait\n\n@heading A\n";
    await expect(insertionRange(text, 0, 0)).toEqual({ start: 26, end: 26 });
    await expect(insertionRange(text, 5, 12)).toEqual({ start: 26, end: 26 });
    await expect(insertionRange(text, 27, 30)).toEqual({ start: 27, end: 30 });
    await expect(insertionRange("@layout table", 3, 3)).toEqual({ start: 13, end: 13 });
    // Text that does not start with the layout line (a half-written draft) is left alone.
    await expect(insertionRange("hello", 0, 0)).toEqual({ start: 0, end: 0 });
  },
};

export const ABlockStartsOnItsOwnLine: Story = {
  play: async () => {
    await expect(asBlock("ab", 2, "@page_break")).toBe("\n@page_break\n");
    await expect(asBlock("ab\n", 3, "@page_break")).toBe("@page_break\n");
    await expect(asBlock("", 0, "@page_break")).toBe("@page_break\n");
  },
};

export const PlaceholdersAreWrittenWithOrWithoutAName: Story = {
  play: async () => {
    await expect(placeholder("req", "title")).toBe("{{req.title}}");
    await expect(placeholder(null, "project_name")).toBe("{{project_name}}");
  },
};

export const WidgetLinesQuoteTextAndLeaveNumbersBare: Story = {
  play: async () => {
    const [register, figures] = buildWidgets() as [ReportWidget, ReportWidget];
    await expect(widgetLine(figures, {})).toBe("[[widget.risk_management.risk-register.figures]]");
    await expect(widgetLine(register, { min_rating: 9, owner: 'Ada "A" Lovelace' }))
      .toBe('[[widget.risk_management.risk-register.register min_rating=9 owner="Ada \\"A\\" Lovelace"]]');
    // Unset and empty settings are left out so the report's own default applies.
    await expect(widgetLine(register, { min_rating: null, owner: "" })).toBe("[[widget.risk_management.risk-register.register]]");
  },
};

export const ADiffMarksAddedAndRemovedLines: Story = {
  play: async () => {
    await expect(diffLines("a\nb\nc", "a\nx\nc")).toEqual([
      { kind: "same", text: "a" }, { kind: "remove", text: "b" }, { kind: "add", text: "x" }, { kind: "same", text: "c" },
    ]);
    await expect(diffLines("", "a")).toEqual([{ kind: "add", text: "a" }]);
    await expect(diffLines("a", "a").every((line) => line.kind === "same")).toBe(true);
  },
};

export const ATooLargeDiffIsShownAsReplacedNotComputed: Story = {
  play: async () => {
    const big = Array.from({ length: 2100 }, (_, i) => `line ${i}`).join("\n");
    const other = Array.from({ length: 2100 }, (_, i) => `row ${i}`).join("\n");
    const result = diffLines(big, other);
    await expect(result.filter((l) => l.kind === "remove")).toHaveLength(2100);
    await expect(result.filter((l) => l.kind === "add")).toHaveLength(2100);
  },
};
