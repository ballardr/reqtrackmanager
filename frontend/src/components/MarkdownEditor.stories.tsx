import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { MarkdownEditor } from "./MarkdownEditor";

/** The Markdown editing control: Write with a toolbar, and Preview. */
const meta: Meta = { title: "Components/MarkdownEditor" };
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
