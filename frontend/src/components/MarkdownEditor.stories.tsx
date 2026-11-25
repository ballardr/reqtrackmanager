import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { chooseMarkdownView, markdownViewState } from "../testing/markdownViews";
import { buildFileAsset } from "../testing/storybook-helpers";
import { MarkdownEditor } from "./MarkdownEditor";
import { MarkdownImageSourceProvider } from "./MarkdownImageSource";

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
    await chooseMarkdownView(canvasElement, "Preview");
    await expect(canvas.getByRole("heading", { level: 4, name: "Heading" })).toBeInTheDocument();
    await expect(canvas.getAllByRole("listitem")).toHaveLength(2);
    await expect(await canvas.findByRole("img", { name: "Diagram: flowchart" }, { timeout: 20_000 })).toBeInTheDocument();
    // The toolbar belongs to the Write view.
    await expect(canvas.queryByRole("button", { name: "Bold" })).toBeNull();
    await chooseMarkdownView(canvasElement, "Write");
    await expect((canvas.getByRole("textbox", { name: "Notes" }) as HTMLTextAreaElement).value).toContain("## Heading");
  },
};

export const EmptyPreviewSaysSo: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await chooseMarkdownView(canvasElement, "Preview");
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
    await waitFor(() => expect(canvasElement.querySelector(".visual-markdown-content")).not.toBeNull());
    // The Visual view's toolbar appears once the person works in the field.
    await expect(canvas.queryByRole("toolbar", { name: "Text formatting" })).toBeNull();
    await userEvent.click(await canvas.findByRole("textbox", { name: "Notes" }));
    await expect(await canvas.findByRole("toolbar", { name: "Text formatting" })).toBeInTheDocument();
    await chooseMarkdownView(canvasElement, "Write");
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
    await waitFor(() => expect(canvasElement.querySelector("textarea")).not.toBeNull());
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
    await expect(await markdownViewState(canvasElement)).toEqual({ offered: ["Write", "Preview"], shown: "Write" });
    await userEvent.type(canvas.getByRole("textbox", { name: "Comment" }), "Needs **review**");
    await chooseMarkdownView(canvasElement, "Preview");
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
    await expect((await markdownViewState(canvasElement)).offered).toEqual(["Visual", "Write", "Preview"]);
    // The source stays exactly as stored (the underscore is not escaped).
    await expect(canvas.getByRole("textbox", { name: "Description" })).toHaveValue("The gain is \\( g_1 \\) at **all** times.");
    await chooseMarkdownView(canvasElement, "Preview");
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
    await expect((await markdownViewState(canvasElement)).shown).toBe("Write");
    await chooseMarkdownView(canvasElement, "Preview");
    await chooseMarkdownView(canvasElement, "Write");
    await expect(localStorage.getItem(VIEW_KEY)).toBe("visual");
  },
};

/** A narrow pop-over leaves the formatting buttons out; the view switch stays. */
export const ToolbarCanBeLeftOut: Story = {
  render: () => <MarkdownEditor simple toolbar={false} value="" onChange={() => {}} ariaLabel="Reply" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("toolbar")).toBeNull();
    await expect((await markdownViewState(canvasElement)).offered).toContain("Preview");
    await userEvent.click(canvas.getByRole("textbox", { name: "Reply" }));
    await expect(await canvas.findByRole("group", { name: "Editor view" })).toBeInTheDocument();
    await expect(canvas.queryByRole("toolbar")).toBeNull();
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
    // A resting field shows neither the toolbar nor the view switch.
    await expect(canvas.queryByRole("group", { name: "Editor view" })).toBeNull();
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
    await expect(canvas.queryByRole("group", { name: "Editor view" })).toBeNull();
  },
};

/** Tab into the field shows its toolbar and Shift+Tab reaches it; Tab out of the field hides it. */
export const KeyboardReachesTheToolbarAndLeavingHidesIt: Story = {
  render: () => (
    <>
      <MarkdownEditor value="" onChange={() => {}} ariaLabel="Notes" rows={3} />
      <button type="button">Outside</button>
    </>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await expect(canvas.getByRole("textbox", { name: "Notes" })).toHaveFocus();
    await expect(await canvas.findByRole("toolbar", { name: "Formatting" })).toBeInTheDocument();
    // The last control of the toolbar row is the view switch.
    await userEvent.tab({ shift: true });
    await expect(canvas.getByRole("button", { name: "Preview" })).toHaveFocus();
    await expect(canvas.getByRole("toolbar", { name: "Formatting" })).toBeInTheDocument();
    canvas.getByRole("button", { name: "Outside" }).focus();
    await waitFor(() => expect(canvas.queryByRole("toolbar")).toBeNull());
  },
};

/** The toolbar is a row of its own that appears when the field is first used, so the field moves down by that row only. */
export const TheToolbarRowTakesNoRoomWhileTheFieldRests: Story = {
  render: () => (
    <>
      <MarkdownEditor value="text" onChange={() => {}} ariaLabel="Notes" />
      <button type="button">After</button>
    </>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const area = canvas.getByRole("textbox", { name: "Notes" });
    const before = area.getBoundingClientRect().top;
    await userEvent.click(area);
    const toolbar = await canvas.findByRole("toolbar", { name: "Formatting" });
    await waitFor(() => expect(area.getBoundingClientRect().top).toBeGreaterThan(before));
    // The shift is the toolbar row and the gap under it, nothing more: no band was reserved while the field rested.
    const shift = area.getBoundingClientRect().top - before;
    const slot = toolbar.closest<HTMLElement>("[data-active-field-toolbar]")!;
    const gap = parseFloat(getComputedStyle(slot.parentElement!).rowGap) || 0;
    await expect(Math.abs(shift - (slot.getBoundingClientRect().height + gap))).toBeLessThan(2);
  },
};

/** A press that first uses the field draws the toolbar on release, so the text does not move between press and release. */
export const TheToolbarAppearsAfterThePointerIsReleased: Story = {
  render: () => <MarkdownEditor value="text" onChange={() => {}} ariaLabel="Notes" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const area = canvas.getByRole("textbox", { name: "Notes" });
    const before = area.getBoundingClientRect().top;
    // One user session, so the release belongs to the press.
    const user = userEvent.setup();
    await user.pointer({ keys: "[MouseLeft>]", target: area });
    await expect(canvas.queryByRole("toolbar")).toBeNull();
    await expect(area.getBoundingClientRect().top).toBe(before);
    await user.pointer({ keys: "[/MouseLeft]", target: area });
    await expect(await canvas.findByRole("toolbar", { name: "Formatting" })).toBeInTheDocument();
  },
};

/** The box of an empty field is the same height in Visual, Write and Preview, and stays equal after typing and clearing. */
export const EmptyFieldIsOneHeightInEveryView: Story = {
  beforeEach: () => { localStorage.setItem(VIEW_KEY, "visual"); },
  render: () => {
    function Both() {
      const [value, setValue] = useState("");
      return <MarkdownEditor math value={value} onChange={setValue} ariaLabel="Notes" />;
    }
    return <Both />;
  },
  play: async ({ canvasElement }) => {
    const heights = () => Math.round(canvasElement.querySelector<HTMLElement>(".md-box")?.getBoundingClientRect().height ?? 0);
    await waitFor(() => expect(canvasElement.querySelector(".visual-markdown-content")).not.toBeNull());
    const visual = heights();
    await chooseMarkdownView(canvasElement, "Write");
    const write = heights();
    await chooseMarkdownView(canvasElement, "Preview");
    const preview = heights();
    await expect([visual, write, preview]).toEqual([write, write, write]);
    // Two lines of the field's own line height plus its padding and border, the same as the boxes beside it.
    await expect(write).toBeLessThan(90);
    await chooseMarkdownView(canvasElement, "Write");
    const area = within(canvasElement).getByRole("textbox", { name: "Notes" });
    await userEvent.type(area, "a");
    await userEvent.clear(area);
    await expect(heights()).toBe(write);
  },
};

/** A field given more lines keeps that minimum in every view. */
export const RowsSetTheMinimumOfEveryView: Story = {
  beforeEach: () => { localStorage.setItem(VIEW_KEY, "visual"); },
  render: () => <MarkdownEditor value="" onChange={() => {}} ariaLabel="Notes" rows={5} />,
  play: async ({ canvasElement }) => {
    const heights = () => Math.round(canvasElement.querySelector<HTMLElement>(".md-box")?.getBoundingClientRect().height ?? 0);
    await waitFor(() => expect(canvasElement.querySelector(".visual-markdown-content")).not.toBeNull());
    const visual = heights();
    await chooseMarkdownView(canvasElement, "Write");
    const write = heights();
    await chooseMarkdownView(canvasElement, "Preview");
    await expect([visual, write]).toEqual([heights(), heights()]);
    await expect(write).toBeGreaterThan(110);
  },
};

/** Pressing the Preview box (which can take focus) uses the field again and brings the view switch back. */
export const PressingThePreviewBringsTheViewSwitchBack: Story = {
  render: () => (
    <>
      <MarkdownEditor simple value="**formatted**" onChange={() => {}} ariaLabel="Notes" />
      <button type="button">Outside</button>
    </>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await chooseMarkdownView(canvasElement, "Preview");
    await userEvent.click(canvas.getByRole("button", { name: "Outside" }));
    await waitFor(() => expect(canvas.queryByRole("group", { name: "Editor view" })).toBeNull());
    await userEvent.click(canvas.getByRole("region", { name: "Preview" }));
    await expect(await canvas.findByRole("group", { name: "Editor view" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Preview" })).toHaveAttribute("aria-pressed", "true");
  },
};

/** With a caption line the switch ends it: nothing is added or moved when the field is used, in any view. */
export const TheViewSwitchSitsOnTheCaptionLineAndNothingMoves: Story = {
  beforeEach: () => { localStorage.setItem(VIEW_KEY, "write"); },
  render: () => (
    <MarkdownEditor
      value="" onChange={() => {}} ariaLabel="Notes" simple toolbar={false}
      renderCaption={(viewSwitch) => <span className="field-caption"><span>Notes</span><span className="field-caption__actions">{viewSwitch}</span></span>}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const area = canvas.getByRole("textbox", { name: "Notes" });
    const caption = canvasElement.querySelector<HTMLElement>(".field-caption")!;
    const captionBefore = caption.getBoundingClientRect().height;
    const areaBefore = area.getBoundingClientRect().top;
    await expect(canvas.queryByRole("group", { name: "Editor view" })).toBeNull();
    await userEvent.click(area);
    const group = await canvas.findByRole("group", { name: "Editor view" });
    await expect(caption.contains(group)).toBe(true);
    await expect(caption.getBoundingClientRect().height).toBe(captionBefore);
    await expect(area.getBoundingClientRect().top).toBe(areaBefore);
    // Pressing Preview replaces the text area, and the switch stays to return to Write.
    await userEvent.click(canvas.getByRole("button", { name: "Preview" }));
    await expect(await canvas.findByRole("group", { name: "Editor view" })).toBeInTheDocument();
    await expect(canvasElement.querySelector(".md-box")!.getBoundingClientRect().top).toBe(areaBefore);
  },
};

/** Choosing a view changes that field only: the other fields on the form keep theirs, and a field drawn later starts in the choice. */
export const AViewIsChosenPerField: Story = {
  beforeEach: () => { localStorage.setItem(VIEW_KEY, "visual"); return () => localStorage.removeItem(VIEW_KEY); },
  render: () => (
    <>
      <MarkdownEditor value="" onChange={() => {}} ariaLabel="First" />
      <MarkdownEditor value="" onChange={() => {}} ariaLabel="Second" />
    </>
  ),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(canvasElement.querySelectorAll(".visual-markdown-content")).toHaveLength(2));
    await chooseMarkdownView(canvasElement, "Write", 0);
    await waitFor(() => expect(canvasElement.querySelectorAll("textarea")).toHaveLength(1));
    // The second field is still Visual and has not moved to Write.
    await expect(canvasElement.querySelectorAll(".visual-markdown-content")).toHaveLength(1);
    await expect(localStorage.getItem(VIEW_KEY)).toBe("write");
  },
};

const PLOT = buildFileAsset({ id: "3f2c9a52-6c1e-4f6e-9b7a-0a1b2c3d4e5f", filename: "plot.png", content_type: "image/png" });

/** The Write view's Picture button puts the chosen attachment in the text at the cursor, on a paragraph of its own. */
export const ThePictureButtonInsertsAnAttachmentInTheWriteView: Story = {
  render: () => (
    <MarkdownImageSourceProvider files={[PLOT]}>
      <Harness initial="Intro" />
    </MarkdownImageSourceProvider>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(document.body);
    const area = canvas.getByRole("textbox", { name: "Notes" }) as HTMLTextAreaElement;
    area.focus();
    area.setSelectionRange(5, 5);
    await userEvent.click(await canvas.findByRole("button", { name: "Picture" }));
    await userEvent.click(await page.findByRole("button", { name: "Picture plot.png" }));
    await userEvent.type(await page.findByRole("textbox", { name: "Alternative text" }), "A plot");
    await userEvent.click(page.getByRole("button", { name: "Insert" }));
    await expect(canvas.getByTestId("stored").textContent).toBe(`Intro\n\n![A plot](attachment:${PLOT.id})`);
  },
};

/** A comment box (`simple`) holds text only, so it has no Picture button even inside a record page. */
export const ACommentBoxOffersNoPicture: Story = {
  render: () => (
    <MarkdownImageSourceProvider files={[PLOT]}>
      <MarkdownEditor value="" onChange={() => {}} ariaLabel="Comment" rows={3} simple />
    </MarkdownImageSourceProvider>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("textbox", { name: "Comment" }));
    await expect(await canvas.findByRole("button", { name: "Bold" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Picture" })).toBeNull();
  },
};
