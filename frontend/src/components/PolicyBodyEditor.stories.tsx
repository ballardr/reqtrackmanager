import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildPolicyBody } from "../testing/storybook-helpers";
import { PolicyBodyEditor } from "./PolicyBodyEditor";

/** The document the editor reported last. */
function lastReported(onChange: unknown): string {
  const calls = (onChange as ReturnType<typeof fn>).mock.calls;
  return JSON.stringify(calls[calls.length - 1]?.[0] ?? null);
}

/** The visual editor for a policy body (TipTap, limited to the server's vocabulary). */
const meta: Meta<typeof PolicyBodyEditor> = {
  title: "Components/PolicyBodyEditor",
  component: PolicyBodyEditor,
  args: { label: "Policy text", value: buildPolicyBody("Existing text."), onChange: fn() },
};
export default meta;

type Story = StoryObj<typeof PolicyBodyEditor>;

/** The editable area is a named textbox, with the formatting toolbar above it. */
export const ShowsToolbarAndText: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("textbox", { name: "Policy text" })).toHaveTextContent("Existing text.");
    const toolbar = canvas.getByRole("toolbar", { name: "Text formatting" });
    for (const name of ["Bold", "Italic", "Heading 1", "Bulleted list", "Numbered list", "Quotation", "Link", "Undo"]) {
      await expect(within(toolbar).getByRole("button", { name })).toBeInTheDocument();
    }
    await expect(within(toolbar).queryByRole("button", { name: "Remove link" })).not.toBeInTheDocument();
  },
};

/** Applying a style to the selected text reports the document, with the style as a mark on that text. */
export const ReportsTheDocumentAfterEdits: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByRole("textbox", { name: "Policy text" });
    await userEvent.click(box);
    // Selected through the DOM, not Ctrl+A: that key selects everything on Linux but moves the caret on macOS.
    window.getSelection()?.selectAllChildren(box);
    await userEvent.click(canvas.getByRole("button", { name: "Bold" }));
    await waitFor(() => {
      expect(lastReported(args.onChange)).toContain('"type":"bold"');
      expect(lastReported(args.onChange)).toContain("Existing text.");
    });
  },
};

/** A link needs an https, http or mailto address; anything else is refused with a message. */
export const RefusesUnsafeLinkAddresses: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByRole("textbox", { name: "Policy text" });
    await userEvent.click(box);
    window.getSelection()?.selectAllChildren(box);
    await userEvent.click(canvas.getByRole("button", { name: "Link" }));
    const address = canvas.getByRole("textbox", { name: "Web address" });
    await userEvent.type(address, "javascript:alert(1)");
    await userEvent.click(canvas.getByRole("button", { name: "Apply link" }));
    await expect(canvas.getByText("Enter an address starting with https://, http:// or mailto:.")).toBeInTheDocument();
    await userEvent.clear(address);
    await userEvent.type(address, "https://example.org/policy");
    await userEvent.click(canvas.getByRole("button", { name: "Apply link" }));
    await waitFor(() => expect(lastReported(args.onChange)).toContain("https://example.org/policy"));
    await expect(canvas.getByRole("button", { name: "Remove link" })).toBeInTheDocument();
    await expect(lastReported(args.onChange)).toContain("Existing text.");
  },
};

/** With nothing selected, applying a link inserts the address as the linked text. */
export const LinkWithNoSelectionInsertsTheAddress: Story = {
  args: { value: { type: "doc", content: [] } },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("textbox", { name: "Policy text" }));
    await userEvent.click(canvas.getByRole("button", { name: "Link" }));
    await userEvent.type(canvas.getByRole("textbox", { name: "Web address" }), "mailto:privacy@example.org{Enter}");
    await waitFor(() => expect(lastReported(args.onChange)).toContain('"text":"mailto:privacy@example.org"'));
    await expect(lastReported(args.onChange)).toContain('"href":"mailto:privacy@example.org"');
  },
};
