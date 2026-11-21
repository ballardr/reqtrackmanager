import type { Meta, StoryObj } from "@storybook/react-vite";
import { useCallback, useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { VisualMarkdownEditor } from "./VisualMarkdownEditor";

/** The Visual view of a Markdown field: formatted editing that stores Markdown. */
const meta: Meta = { title: "Components/VisualMarkdownEditor" };
export default meta;

type Story = StoryObj;

/** Holds the value as a form would, and shows what is stored. */
function Harness({ initial = "", onReport, onBlocked }: { initial?: string; onReport?: (value: string) => void; onBlocked?: () => void }) {
  const [value, setValue] = useState(initial);
  const change = useCallback((next: string) => { setValue(next); onReport?.(next); }, [onReport]);
  const blocked = useCallback(() => onBlocked?.(), [onBlocked]);
  return (
    <>
      <VisualMarkdownEditor value={value} onChange={change} onBlocked={blocked} ariaLabel="Notes" rows={4} />
      <button type="button" onClick={() => setValue("Replaced from outside")}>Replace</button>
      <pre data-testid="stored">{value}</pre>
    </>
  );
}

const stored = (canvas: ReturnType<typeof within>) => canvas.getByTestId("stored");

export const ShowsFormattedContent: Story = {
  render: () => <Harness initial={"## Plan\n\nSome **bold** and a [link](https://example.org).\n\n- one\n- two\n\n| A | B |\n| --- | --- |\n| 1 | 2 |"} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByRole("textbox", { name: "Notes" });
    await expect(within(box).getByRole("heading", { name: "Plan" })).toBeInTheDocument();
    await expect(within(box).getByRole("link", { name: "link" })).toHaveAttribute("href", "https://example.org");
    await expect(within(box).getAllByRole("listitem")).toHaveLength(2);
    await expect(within(box).getByRole("cell", { name: "2" })).toBeInTheDocument();
    await expect(box.textContent).not.toContain("**");
  },
};

export const OpeningATextDoesNotReportAChange: Story = {
  render: () => <Harness initial="Some _text_ here" onReport={fn()} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("textbox", { name: "Notes" });
    await new Promise((resolve) => setTimeout(resolve, 500));
    // `_text_` would be rewritten as `*text*` if the editor wrote it back.
    await expect(stored(canvas)).toHaveTextContent("Some _text_ here");
  },
};

export const TypingMarkdownShortcutsFormatsAndStoresSource: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("textbox", { name: "Notes" }));
    await userEvent.keyboard("## Title{Enter}- first{Enter}second");
    await waitFor(() => expect(stored(canvas)).toHaveTextContent("## Title"));
    await expect(stored(canvas)).toHaveTextContent("- first");
    await expect(stored(canvas)).toHaveTextContent("- second");
  },
};

export const ToolbarFormatsTheSelection: Story = {
  render: () => <Harness initial="make this bold" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByRole("textbox", { name: "Notes" });
    await userEvent.click(box);
    window.getSelection()?.selectAllChildren(box);
    await userEvent.click(canvas.getByRole("button", { name: "Bold" }));
    await waitFor(() => expect(stored(canvas)).toHaveTextContent("**make this bold**"));
  },
};

export const InsertsATableWithRowAndColumnActions: Story = {
  render: () => <Harness initial="Intro" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByRole("textbox", { name: "Notes" });
    await userEvent.click(box);
    await userEvent.click(canvas.getByRole("button", { name: "Table" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Add row below" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Add row below" }));
    await waitFor(() => expect(stored(canvas).textContent).toMatch(/\| --- \| --- \| --- \|/));
    await expect(within(box).getAllByRole("row")).toHaveLength(4);
    await userEvent.click(canvas.getByRole("button", { name: "Delete table" }));
    await waitFor(() => expect(stored(canvas).textContent).not.toContain("---"));
  },
};

export const DiagramBlockEditsSourceBesideTheDrawing: Story = {
  render: () => <Harness initial="Intro" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("textbox", { name: "Notes" }));
    await userEvent.click(canvas.getByRole("button", { name: "Diagram" }));
    await waitFor(() => expect(stored(canvas)).toHaveTextContent("```mermaid"));
    await expect(await canvas.findByRole("img", { name: "Diagram: flowchart" }, { timeout: 20_000 })).toBeInTheDocument();
    await expect(canvas.getByText("Diagram source")).toBeInTheDocument();
  },
};

export const CodeBlockWithAFenceInItKeepsItsMeaning: Story = {
  render: () => <Harness initial={"````\n```\ninner\n```\n````"} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByRole("textbox", { name: "Notes" });
    await userEvent.click(box);
    const code = box.querySelector(".visual-code");
    if (!code) throw new Error("The code block is missing.");
    window.getSelection()?.selectAllChildren(code);
    window.getSelection()?.collapseToEnd();
    await userEvent.keyboard("x");
    await waitFor(() => expect(stored(canvas).textContent).toBe("````\n```\ninner\n```x\n````"));
  },
};

export const PastedMarkdownOffersConversion: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByRole("textbox", { name: "Notes" });
    await userEvent.click(box);
    await userEvent.paste("## Findings\n\n- first\n- second");
    await expect(await canvas.findByRole("status")).toHaveTextContent("The pasted text looks like Markdown.");
    await expect(within(box).queryByRole("heading")).toBeNull();
    await userEvent.click(canvas.getByRole("button", { name: "Convert to formatting" }));
    await expect(await within(box).findByRole("heading", { name: "Findings" })).toBeInTheDocument();
    await expect(within(box).getAllByRole("listitem")).toHaveLength(2);
    await waitFor(() => expect(stored(canvas).textContent).toBe("## Findings\n\n- first\n- second"));
    await expect(canvas.queryByRole("status")).toBeNull();
  },
};

export const PastedInlineMarkdownStaysAsTypedUntilConverted: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByRole("textbox", { name: "Notes" });
    await userEvent.click(box);
    await userEvent.paste("a **bold** claim");
    await expect(await canvas.findByRole("status")).toHaveTextContent("looks like Markdown");
    await expect(box.querySelector("strong")).toBeNull();
    await userEvent.click(canvas.getByRole("button", { name: "Convert to formatting" }));
    await waitFor(() => expect(box.querySelector("strong")).toHaveTextContent("bold"));
    await waitFor(() => expect(stored(canvas).textContent).toBe("a **bold** claim"));
  },
};

export const KeepAsTypedDismissesTheOffer: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("textbox", { name: "Notes" }));
    await userEvent.paste("> a quoted claim");
    await userEvent.click(await canvas.findByRole("button", { name: "Keep as typed" }));
    await expect(canvas.queryByRole("status")).toBeNull();
    await waitFor(() => expect(stored(canvas).textContent).toBe("&gt; a quoted claim"));
  },
};

export const PlainPasteGetsNoOffer: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("textbox", { name: "Notes" }));
    await userEvent.paste("Just a sentence.");
    await waitFor(() => expect(stored(canvas)).toHaveTextContent("Just a sentence."));
    await expect(canvas.queryByRole("status")).toBeNull();
  },
};

export const ReportsWhyATextCannotBeEditedVisually: Story = {
  render: () => <Harness initial="<div>raw</div>" onBlocked={fn()} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.queryByRole("textbox", { name: "Notes" })).toBeNull());
    await expect(stored(canvas)).toHaveTextContent("<div>raw</div>");
  },
};

export const AValueChangedFromOutsideReplacesTheContent: Story = {
  render: () => <Harness initial="Original" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByRole("textbox", { name: "Notes" });
    await userEvent.click(canvas.getByRole("button", { name: "Replace" }));
    await waitFor(() => expect(box).toHaveTextContent("Replaced from outside"));
  },
};

/** The Visual view's toolbar shows while focus is in the field and its space is kept while it is hidden. */
export const ToolbarShowsOnlyWhileTheFieldIsActive: Story = {
  render: () => (
    <>
      <Harness initial="Some text" />
      <button type="button">Outside</button>
    </>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByRole("textbox", { name: "Notes" });
    await expect(canvas.queryByRole("toolbar")).toBeNull();
    const before = box.getBoundingClientRect().top;
    await userEvent.click(box);
    await expect(await canvas.findByRole("toolbar", { name: "Text formatting" })).toBeInTheDocument();
    await expect(box.getBoundingClientRect().top).toBe(before);
    // The link entry is part of the field: working in it keeps the toolbar.
    await userEvent.click(canvas.getByRole("button", { name: "Link" }));
    await expect(canvas.getByRole("textbox", { name: "Web address" })).toHaveFocus();
    await expect(canvas.getByRole("toolbar", { name: "Text formatting" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Outside" }));
    await waitFor(() => expect(canvas.queryByRole("toolbar")).toBeNull());
  },
};
