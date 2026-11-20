import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { MarkdownEditor } from "./MarkdownEditor";

const VIEW_KEY = "reqtrack.markdownEditorView";

/** The Markdown editing control: Visual, Write with a toolbar, and Preview. */
const meta: Meta = {
  title: "Components/MarkdownEditor",
  // The stories below that drive the source open in Write; the Visual stories choose their own view.
  beforeEach: () => {
    localStorage.setItem(VIEW_KEY, "write");
    return () => localStorage.removeItem(VIEW_KEY);
  },
};
export default meta;

type Story = StoryObj;

/** The editor owns no state; this harness supplies what a form would, and shows the stored value. */
function Harness({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <MarkdownEditor value={value} onChange={setValue} ariaLabel="Notes" rows={4} />
      <pre data-testid="stored">{value}</pre>
    </>
  );
}

export const ToolbarFormatsTheSelection: Story = {
  render: () => <Harness initial="make this bold" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const area = canvas.getByRole("textbox", { name: "Notes" }) as HTMLTextAreaElement;
    area.focus();
    area.setSelectionRange(5, 9);
    await userEvent.click(canvas.getByRole("button", { name: "Bold" }));
    await expect(canvas.getByTestId("stored")).toHaveTextContent("make **this** bold");
    await waitFor(() => expect(area.selectionStart).toBe(7));
  },
};

export const DiagramButtonInsertsAMermaidBlock: Story = {
  render: () => <Harness initial="Intro" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const area = canvas.getByRole("textbox", { name: "Notes" }) as HTMLTextAreaElement;
    area.focus();
    area.setSelectionRange(5, 5);
    await userEvent.click(canvas.getByRole("button", { name: "Diagram" }));
    await expect(canvas.getByTestId("stored")).toHaveTextContent("```mermaid");
  },
};

export const PreviewShowsTheFormattedText: Story = {
  render: () => <Harness initial={"## Heading\n\n- one\n- two\n\n```mermaid\nflowchart LR\n  A --> B\n```"} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("tab", { name: "Preview" }));
    await expect(canvas.getByRole("heading", { level: 4, name: "Heading" })).toBeInTheDocument();
    await expect(canvas.getAllByRole("listitem")).toHaveLength(2);
    await expect(await canvas.findByRole("img", { name: "Diagram: flowchart" }, { timeout: 20_000 })).toBeInTheDocument();
    // The toolbar belongs to the Write view.
    await expect(canvas.queryByRole("button", { name: "Bold" })).toBeNull();
    await userEvent.click(canvas.getByRole("tab", { name: "Write" }));
    await expect((canvas.getByRole("textbox", { name: "Notes" }) as HTMLTextAreaElement).value).toContain("## Heading");
  },
};

export const EmptyPreviewSaysSo: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("tab", { name: "Preview" }));
    await expect(canvas.getByText("Nothing to preview.")).toBeInTheDocument();
  },
};

export const TypingIsStoredAsSource: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Notes" }), "plain *text*");
    await expect(canvas.getByTestId("stored")).toHaveTextContent("plain *text*");
  },
};

export const OpensInTheVisualViewUntilWriteIsChosen: Story = {
  beforeEach: () => { localStorage.removeItem(VIEW_KEY); },
  render: () => <Harness initial="Some **bold** text" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("tab", { name: "Visual", selected: true })).toBeInTheDocument();
    await expect(await canvas.findByRole("toolbar", { name: "Text formatting" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("tab", { name: "Write" }));
    await expect((canvas.getByRole("textbox", { name: "Notes" }) as HTMLTextAreaElement).value).toBe("Some **bold** text");
    // The choice is remembered for the next field.
    await expect(localStorage.getItem(VIEW_KEY)).toBe("write");
  },
};

export const ATextTheVisualViewWouldChangeOpensInWriteWithTheReason: Story = {
  beforeEach: () => { localStorage.setItem(VIEW_KEY, "visual"); },
  render: () => <Harness initial={"A task list:\n\n- [ ] open\n- [x] done"} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("tab", { name: "Write", selected: true })).toBeInTheDocument());
    await expect(canvas.getByRole("status")).toHaveTextContent("The Visual view is unavailable");
    await expect((canvas.getByRole("textbox", { name: "Notes" }) as HTMLTextAreaElement).value).toContain("- [ ] open");
    // A fallback is not a choice: the stored preference is unchanged.
    await expect(localStorage.getItem(VIEW_KEY)).toBe("visual");
  },
};

export const MathematicsKeepsTheFieldInWrite: Story = {
  beforeEach: () => { localStorage.setItem(VIEW_KEY, "visual"); },
  render: () => <Harness initial="Energy is $E = mc^2$." />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("status")).toHaveTextContent("contains mathematics"));
  },
};

/** A comment box and a short note offer Write and Preview only. */
export const SimpleEditorHasNoVisualTab: Story = {
  render: () => {
    function Simple() {
      const [value, setValue] = useState("");
      return <MarkdownEditor simple value={value} onChange={setValue} ariaLabel="Comment" rows={2} />;
    }
    return <Simple />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("tab", { name: "Visual" })).toBeNull();
    await expect(canvas.getByRole("tab", { name: "Write" })).toHaveAttribute("aria-selected", "true");
    await userEvent.type(canvas.getByRole("textbox", { name: "Comment" }), "Needs **review**");
    await userEvent.click(canvas.getByRole("tab", { name: "Preview" }));
    await waitFor(() => expect(canvasElement.querySelector("strong")).toHaveTextContent("review"));
  },
};

/** A field that holds equations is edited as source and previewed with the equations drawn. */
export const MathEditorDrawsEquationsInPreview: Story = {
  render: () => {
    function Math() {
      const [value, setValue] = useState("The gain is \\( g_1 \\) at **all** times.");
      return <MarkdownEditor math value={value} onChange={setValue} ariaLabel="Description" rows={2} />;
    }
    return <Math />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("tab", { name: "Visual" })).toBeNull();
    // The visual writer would escape the underscore, so the source stays exactly as stored.
    await expect(canvas.getByRole("textbox", { name: "Description" })).toHaveValue("The gain is \\( g_1 \\) at **all** times.");
    await userEvent.click(canvas.getByRole("tab", { name: "Preview" }));
    await waitFor(() => expect(canvasElement.querySelector(".math-text")).not.toBeNull());
    await expect(canvasElement.querySelector("strong")).toHaveTextContent("all");
  },
};

/** A remembered Visual choice never changes a simple editor, and a simple editor never changes the remembered choice. */
export const SimpleEditorLeavesTheRememberedViewAlone: Story = {
  beforeEach: () => {
    localStorage.setItem(VIEW_KEY, "visual");
    return () => localStorage.removeItem(VIEW_KEY);
  },
  render: () => <MarkdownEditor simple value="" onChange={() => {}} ariaLabel="Comment" rows={2} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("tab", { name: "Write" })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(canvas.getByRole("tab", { name: "Preview" }));
    await userEvent.click(canvas.getByRole("tab", { name: "Write" }));
    await expect(localStorage.getItem(VIEW_KEY)).toBe("visual");
  },
};

/** A narrow pop-over leaves the formatting buttons out; the Write and Preview tabs stay. */
export const ToolbarCanBeLeftOut: Story = {
  render: () => <MarkdownEditor simple toolbar={false} value="" onChange={() => {}} ariaLabel="Reply" rows={2} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("toolbar")).toBeNull();
    await expect(canvas.getByRole("tab", { name: "Preview" })).toBeInTheDocument();
  },
};
