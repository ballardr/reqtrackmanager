import type { Meta, StoryObj } from "@storybook/react-vite";
import { useCallback, useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildFileAsset } from "../testing/storybook-helpers";
import type { FileAsset } from "../api/types";
import { MarkdownImageSourceProvider } from "./MarkdownImageSource";
import { VisualMarkdownEditor } from "./VisualMarkdownEditor";

/** The Visual view of a Markdown field: formatted editing that stores Markdown. */
const meta: Meta = { title: "Components/VisualMarkdownEditor" };
export default meta;

type Story = StoryObj;

/** Holds the value as a form would, and shows what is stored. */
function Harness({ initial = "", onReport, onBlocked, math, source, placeholder }: {
  initial?: string; placeholder?: string; onReport?: (value: string) => void; onBlocked?: () => void; math?: boolean;
  /** The record's attachments and upload, as its page supplies them; omitted for a field with no record (a create form). */
  source?: { files: FileAsset[]; upload?: (file: File) => Promise<FileAsset> };
}) {
  const [value, setValue] = useState(initial);
  const change = useCallback((next: string) => { setValue(next); onReport?.(next); }, [onReport]);
  const blocked = useCallback(() => onBlocked?.(), [onBlocked]);
  const editor = <VisualMarkdownEditor value={value} onChange={change} onBlocked={blocked} ariaLabel="Notes" rows={4} math={math} textareaProps={placeholder ? { placeholder } : undefined} />;
  return (
    <>
      {source ? <MarkdownImageSourceProvider files={source.files} upload={source.upload}>{editor}</MarkdownImageSourceProvider> : editor}
      <button type="button" onClick={() => setValue("Replaced from outside")}>Replace</button>
      <pre data-testid="stored">{value}</pre>
    </>
  );
}

const PLOT = buildFileAsset({ id: "3f2c9a52-6c1e-4f6e-9b7a-0a1b2c3d4e5f", filename: "plot.png", content_type: "image/png" });

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

/** The Visual view's toolbar shows while the field is in use and takes no room while it rests. */
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
    await expect(box.getBoundingClientRect().top).toBeGreaterThan(before);
    // The link entry is part of the field: working in it keeps the toolbar.
    await userEvent.click(canvas.getByRole("button", { name: "Link" }));
    await expect(canvas.getByRole("textbox", { name: "Web address" })).toHaveFocus();
    await expect(canvas.getByRole("toolbar", { name: "Text formatting" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Outside" }));
    await waitFor(() => expect(canvas.queryByRole("toolbar")).toBeNull());
  },
};

export const ADrawnEquationIsKeptExactlyAsStoredAndChangedInThePanel: Story = {
  render: () => <Harness math initial={"The gain is \\( g_1 \\) at **all** times."} onBlocked={fn()} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(document.body);
    const box = await canvas.findByRole("textbox", { name: "Notes" });
    await waitFor(() => expect(box.querySelector(".math-text")).not.toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 400));
    // Opening writes nothing back, and the TeX is never escaped.
    await expect(stored(canvas)).toHaveTextContent("The gain is \\( g_1 \\) at **all** times.");
    await userEvent.click(within(box).getByRole("button", { name: /Change equation/ }));
    const input = await page.findByRole("textbox", { name: "TeX" });
    await expect(input).toHaveValue("g_1");
    await userEvent.clear(input);
    await userEvent.type(input, "g_2{Enter}");
    await waitFor(() => expect(stored(canvas)).toHaveTextContent("The gain is \\(g_2\\) at **all** times."));
  },
};

export const TheEquationButtonsInsertAnEquationAtTheCursor: Story = {
  render: () => <Harness math />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(document.body);
    const box = await canvas.findByRole("textbox", { name: "Notes" });
    await userEvent.click(box);
    await userEvent.keyboard("Result: ");
    await userEvent.click(await canvas.findByRole("button", { name: "Inline equation" }));
    await userEvent.type(await page.findByRole("textbox", { name: "TeX" }), "a_1 + b_2");
    await waitFor(() => expect(page.getByTestId("math-preview").querySelector(".katex")).not.toBeNull());
    await userEvent.click(page.getByRole("button", { name: "Insert" }));
    await waitFor(() => expect(stored(canvas)).toHaveTextContent("Result: \\(a_1 + b_2\\)"));
    await waitFor(() => expect(box.querySelector(".math-text")).not.toBeNull());
  },
};

export const AFieldWithoutMathematicsStillRefusesEquations: Story = {
  render: () => <Harness initial={"Energy is \\( E \\)."} onBlocked={fn()} />,
  play: async ({ canvasElement, }) => {
    // Without the equation node the writer would escape the TeX, so the field falls back to Write.
    await waitFor(() => expect(within(canvasElement).queryByRole("textbox", { name: "Notes" })).toBeNull());
  },
};

export const ATextWithAPictureOpensVisuallyAndIsNotRewritten: Story = {
  render: () => <Harness initial={`Before.\n\n![A plot](attachment:${PLOT.id} "Figure 1")\n\nAfter.`} onBlocked={fn()} source={{ files: [PLOT] }} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByRole("textbox", { name: "Notes" });
    // The picture is drawn (and falls back to its words here, where no file server answers), and nothing is reported.
    await waitFor(() => expect(box.querySelector(".visual-picture")).not.toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 400));
    await expect(stored(canvas)).toHaveTextContent(`![A plot](attachment:${PLOT.id} "Figure 1")`);
  },
};

export const ThePictureButtonInsertsAPictureAsAParagraphOfItsOwn: Story = {
  render: () => <Harness source={{ files: [PLOT] }} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(document.body);
    await userEvent.click(await canvas.findByRole("textbox", { name: "Notes" }));
    await userEvent.keyboard("Intro");
    await userEvent.click(await canvas.findByRole("button", { name: "Picture" }));
    await userEvent.click(await page.findByRole("button", { name: "Picture plot.png" }));
    await userEvent.type(await page.findByRole("textbox", { name: "Alternative text" }), "A plot");
    await userEvent.click(page.getByRole("button", { name: "Insert" }));
    await waitFor(() => expect(stored(canvas).textContent).toBe(`Intro\n\n![A plot](attachment:${PLOT.id})`));
  },
};

export const PressingAPictureChangesItsWordsAndKeepsItsFile: Story = {
  render: () => <Harness initial={`![Old](attachment:${PLOT.id})`} source={{ files: [PLOT] }} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(document.body);
    const change = await canvas.findByRole("button", { name: /Change picture: Old/ });
    await userEvent.click(change);
    const alt = await page.findByRole("textbox", { name: "Alternative text" });
    await userEvent.clear(alt);
    await userEvent.type(alt, "New");
    await userEvent.type(page.getByRole("textbox", { name: "Caption" }), "Fig 2");
    await userEvent.click(page.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(stored(canvas)).toHaveTextContent(`![New](attachment:${PLOT.id} "Fig 2")`));
  },
};

export const NoPictureButtonWhereThereIsNoRecordToAttachTo: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("textbox", { name: "Notes" }));
    await expect(await canvas.findByRole("button", { name: "Bold" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Picture" })).toBeNull();
  },
};

export const APictureFilePastedIsAttachedAndInserted: Story = {
  render: () => {
    const fresh = buildFileAsset({ id: "55555555-5555-4555-8555-555555555555", filename: "image.png", content_type: "image/png" });
    return <Harness source={{ files: [], upload: fn(async () => fresh) }} />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByRole("textbox", { name: "Notes" });
    await userEvent.click(box);
    const data = new DataTransfer();
    data.items.add(new File(["x"], "image.png", { type: "image/png" }));
    box.dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true }));
    await waitFor(() => expect(stored(canvas)).toHaveTextContent("![](attachment:55555555-5555-4555-8555-555555555555)"));
  },
};

export const AnImageWithAnOutsideAddressStillFallsBackToWrite: Story = {
  render: () => <Harness initial="![tracker](https://example.com/pixel.png)" onBlocked={fn()} source={{ files: [PLOT] }} />,
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).queryByRole("textbox", { name: "Notes" })).toBeNull());
  },
};

/** An empty field shows its hint in the Visual view as the Write view does, and the hint is not part of the text. */
export const EmptyFieldShowsItsHint: Story = {
  render: () => <Harness placeholder="Describe the requirement" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByRole("textbox", { name: "Notes" });
    await waitFor(() => expect(getComputedStyle(box.querySelector("p")!, "::before").content).toContain("Describe the requirement"));
    await userEvent.type(box, "x");
    await waitFor(() => expect(getComputedStyle(box.querySelector("p")!, "::before").content).not.toContain("Describe"));
    await waitFor(() => expect(canvas.getByTestId("stored")).toHaveTextContent(/^x$/));
  },
};
