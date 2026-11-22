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
    await userEvent.click(await canvas.findByRole("button", { name: "Bold" }));
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
    await userEvent.click(await canvas.findByRole("button", { name: "Diagram" }));
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
    // The Visual view's toolbar appears once the person works in the field.
    await expect(canvas.queryByRole("toolbar", { name: "Text formatting" })).toBeNull();
    await userEvent.click(await canvas.findByRole("textbox", { name: "Notes" }));
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

/** A field that holds equations offers all three views and previews them drawn. */
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
    await expect(canvas.getByRole("tab", { name: "Visual" })).toBeInTheDocument();
    // The source stays exactly as stored (the underscore is not escaped).
    await expect(canvas.getByRole("textbox", { name: "Description" })).toHaveValue("The gain is \\( g_1 \\) at **all** times.");
    await userEvent.click(canvas.getByRole("tab", { name: "Preview" }));
    await waitFor(() => expect(canvasElement.querySelector(".math-text")).not.toBeNull());
    await expect(canvasElement.querySelector("strong")).toHaveTextContent("all");
  },
};

/** Only a field declared for mathematics offers the equation buttons. */
export const OnlyAMathematicsFieldOffersTheEquationButtons: Story = {
  render: () => {
    function Both() {
      const [a, setA] = useState("");
      const [b, setB] = useState("");
      return (
        <>
          <MarkdownEditor math value={a} onChange={setA} ariaLabel="With equations" rows={2} />
          <MarkdownEditor value={b} onChange={setB} ariaLabel="Without equations" rows={2} />
        </>
      );
    }
    return <Both />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const frames = Array.from(canvasElement.querySelectorAll(".markdown-editor")) as HTMLElement[];
    // A toolbar is in the accessibility tree only while its field is active.
    await userEvent.click(within(frames[0]).getByRole("textbox", { name: "With equations" }));
    await expect(within(frames[0]).getByRole("button", { name: "Inline equation" })).toBeInTheDocument();
    await expect(within(frames[0]).getByRole("button", { name: "Equation block" })).toBeInTheDocument();
    await userEvent.click(within(frames[1]).getByRole("textbox", { name: "Without equations" }));
    await expect(within(frames[1]).queryByRole("button", { name: "Inline equation" })).toBeNull();
    await expect(canvas.getAllByRole("toolbar")).toHaveLength(1);
  },
};

/** The equation panel opens with the selected text, draws it as typed and inserts it as an inline equation. */
export const InlineEquationButtonOpensAPanelWithALivePreview: Story = {
  render: () => {
    function Math() {
      const [value, setValue] = useState("The area is pi r^2 here");
      return (
        <>
          <MarkdownEditor math value={value} onChange={setValue} ariaLabel="Description" rows={2} />
          <pre data-testid="stored">{value}</pre>
        </>
      );
    }
    return <Math />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(document.body);
    const area = canvas.getByRole("textbox", { name: "Description" }) as HTMLTextAreaElement;
    area.focus();
    area.setSelectionRange(12, 18);
    await userEvent.click(await canvas.findByRole("button", { name: "Inline equation" }));
    const input = await page.findByRole("textbox", { name: "TeX" });
    await expect(input).toHaveValue("pi r^2");
    await userEvent.clear(input);
    await userEvent.type(input, "\\pi r^2");
    await waitFor(() => expect(page.getByTestId("math-preview").querySelector(".katex")).not.toBeNull());
    await userEvent.click(page.getByRole("button", { name: "Insert" }));
    await waitFor(() => expect(canvas.getByTestId("stored")).toHaveTextContent("The area is \\(\\pi r^2\\) here"));
    await waitFor(() => expect(page.queryByTestId("math-preview")).toBeNull());
  },
};

/** An equation block starts on its own line. */
export const EquationBlockIsInsertedAsItsOwnParagraph: Story = {
  render: () => {
    function Math() {
      const [value, setValue] = useState("Intro text");
      return (
        <>
          <MarkdownEditor math value={value} onChange={setValue} ariaLabel="Description" rows={2} />
          <pre data-testid="stored">{value}</pre>
        </>
      );
    }
    return <Math />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(document.body);
    const area = canvas.getByRole("textbox", { name: "Description" }) as HTMLTextAreaElement;
    area.focus();
    area.setSelectionRange(5, 5);
    await userEvent.click(await canvas.findByRole("button", { name: "Equation block" }));
    await userEvent.type(await page.findByRole("textbox", { name: "TeX" }), "x_1 + y_2{Enter}");
    await waitFor(() => expect(area.value).toBe("Intro\n\n$$x_1 + y_2$$\n\n text"));
  },
};

/** The panel refuses TeX that would end the equation early, says why and keeps Insert unavailable. */
export const TheEquationPanelRefusesTeXThatCannotBeStored: Story = {
  render: () => {
    function Math() {
      const [value, setValue] = useState("");
      return <MarkdownEditor math value={value} onChange={setValue} ariaLabel="Description" rows={2} />;
    }
    return <Math />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(document.body);
    await userEvent.click(canvas.getByRole("textbox", { name: "Description" }));
    await userEvent.click(await canvas.findByRole("button", { name: "Inline equation" }));
    const input = await page.findByRole("textbox", { name: "TeX" });
    await expect(page.getByRole("button", { name: "Insert" })).toBeDisabled();
    await userEvent.type(input, "a\\)b");
    await expect(await page.findByRole("alert")).toHaveTextContent("cannot contain");
    await expect(page.getByRole("button", { name: "Insert" })).toBeDisabled();
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

/** The Write view's formatting buttons show only while focus is inside the field, and Tab reaches them. */
export const WriteToolbarShowsOnlyWhileTheFieldIsActive: Story = {
  render: () => (
    <>
      <MarkdownEditor value="some text" onChange={() => {}} ariaLabel="Notes" rows={3} />
      <button type="button">Outside</button>
    </>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("toolbar")).toBeNull();
    await expect(canvas.queryByRole("button", { name: "Bold" })).toBeNull();
    const area = canvas.getByRole("textbox", { name: "Notes" });
    await userEvent.click(area);
    await expect(await canvas.findByRole("toolbar", { name: "Formatting" })).toBeInTheDocument();
    // Pressing a button keeps the focus in the field, so the toolbar stays for the next action.
    await userEvent.click(canvas.getByRole("button", { name: "Bold" }));
    await expect(canvas.getByRole("toolbar", { name: "Formatting" })).toBeInTheDocument();
    // Escape is for the field's own use (a dialog's close): it does not hide the toolbar mid-edit.
    await userEvent.keyboard("{Escape}");
    await expect(canvas.getByRole("toolbar", { name: "Formatting" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Outside" }));
    await waitFor(() => expect(canvas.queryByRole("toolbar")).toBeNull());
  },
};

/** Tab from the Write tab into the toolbar keeps it shown; Tab out of the field hides it. */
export const KeyboardReachesTheToolbarAndLeavingHidesIt: Story = {
  render: () => (
    <>
      <MarkdownEditor value="" onChange={() => {}} ariaLabel="Notes" rows={3} />
      <button type="button">Outside</button>
    </>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    canvas.getByRole("tab", { name: "Write" }).focus();
    await expect(await canvas.findByRole("toolbar", { name: "Formatting" })).toBeInTheDocument();
    await userEvent.tab();
    await expect(canvas.getByRole("button", { name: "Bold" })).toHaveFocus();
    await expect(canvas.getByRole("toolbar", { name: "Formatting" })).toBeInTheDocument();
    canvas.getByRole("button", { name: "Outside" }).focus();
    await waitFor(() => expect(canvas.queryByRole("toolbar")).toBeNull());
  },
};

/** Showing the toolbar does not move the field: its text area sits at the same place with the toolbar hidden or shown. */
export const ShowingTheToolbarDoesNotMoveTheField: Story = {
  render: () => <MarkdownEditor value="text" onChange={() => {}} ariaLabel="Notes" rows={3} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const area = canvas.getByRole("textbox", { name: "Notes" });
    const before = area.getBoundingClientRect().top;
    await userEvent.click(area);
    await expect(await canvas.findByRole("toolbar", { name: "Formatting" })).toBeInTheDocument();
    await expect(area.getBoundingClientRect().top).toBe(before);
  },
};
