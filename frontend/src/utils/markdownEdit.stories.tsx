import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { applyMarkdownFormat } from "./markdownEdit";

/** The pure text edits behind the Markdown editor's toolbar. */
const meta: Meta = { title: "Utils/markdownEdit", render: () => <p>Pure helpers; see the interactions.</p> };
export default meta;

type Story = StoryObj;

export const InlineFormatsWrapTheSelectionAndToggleOff: Story = {
  play: async () => {
    const bold = applyMarkdownFormat("a word here", 2, 6, "bold");
    await expect(bold).toEqual({ value: "a **word** here", selectionStart: 4, selectionEnd: 8 });
    // Applying it again to the wrapped text removes it.
    await expect(applyMarkdownFormat(bold.value, 2, 10, "bold").value).toBe("a word here");
    await expect(applyMarkdownFormat("", 0, 0, "italic")).toEqual({ value: "_italic text_", selectionStart: 1, selectionEnd: 12 });
  },
};

export const LineFormatsApplyToEverySelectedLine: Story = {
  play: async () => {
    await expect(applyMarkdownFormat("one\ntwo\nthree", 0, 7, "bulleted").value).toBe("- one\n- two\nthree");
    await expect(applyMarkdownFormat("one\ntwo", 0, 7, "numbered").value).toBe("1. one\n2. two");
    await expect(applyMarkdownFormat("- one\n- two", 0, 11, "bulleted").value).toBe("one\ntwo");
    await expect(applyMarkdownFormat("a\nb", 2, 2, "quote").value).toBe("a\n> b");
    // A heading replaces an existing heading level.
    await expect(applyMarkdownFormat("### Title", 0, 0, "heading").value).toBe("Title");
    await expect(applyMarkdownFormat("Title", 0, 0, "heading").value).toBe("## Title");
  },
};

export const LinkLeavesTheAddressSelected: Story = {
  play: async () => {
    const result = applyMarkdownFormat("see site now", 4, 8, "link");
    await expect(result.value).toBe("see [site](https://) now");
    await expect(result.value.slice(result.selectionStart, result.selectionEnd)).toBe("https://");
  },
};

export const BlocksStartOnTheirOwnLine: Story = {
  play: async () => {
    const diagram = applyMarkdownFormat("Intro", 5, 5, "diagram");
    await expect(diagram.value.startsWith("Intro\n\n```mermaid\nflowchart LR")).toBe(true);
    await expect(diagram.value.endsWith("\n```")).toBe(true);
    const table = applyMarkdownFormat("", 0, 0, "table");
    await expect(table.value).toContain("| --- | --- |");
    const code = applyMarkdownFormat("x = 1", 0, 5, "code");
    await expect(code.value).toBe("```\nx = 1\n```");
    await expect(code.value.slice(code.selectionStart, code.selectionEnd)).toBe("x = 1");
  },
};
