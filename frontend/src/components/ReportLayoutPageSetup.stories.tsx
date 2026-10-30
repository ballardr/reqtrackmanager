import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, screen, userEvent, within } from "storybook/test";

import { ReportLayoutPageSetup } from "./ReportLayoutPageSetup";

/** Hosts the control with the text it edits, and shows the text so a story can read the rewritten lines. */
function Host({ initial }: { initial: string }) {
  const [text, setText] = useState(initial);
  return (
    <div className="stack">
      <ReportLayoutPageSetup text={text} onChange={setText} />
      <pre aria-label="Text">{text}</pre>
    </div>
  );
}

/** Paper, orientation, margins, mirrored margins and page styles, written into the layout text's header lines. */
const meta: Meta<typeof ReportLayoutPageSetup> = {
  title: "Components/ReportLayoutPageSetup",
  component: ReportLayoutPageSetup,
  render: () => <Host initial={"@layout document\n\n@heading Hello\n"} />,
};
export default meta;

type Story = StoryObj<typeof ReportLayoutPageSetup>;

const text = (canvasElement: HTMLElement) => within(canvasElement).getByLabelText("Text");
const openDialog = async (canvasElement: HTMLElement, name: string) => {
  await userEvent.click(within(canvasElement).getByRole("button", { name }));
  return within(await screen.findByRole("dialog", { name: "Page setup" }));
};

/** The button says the current setup, and a change rewrites only the first line. */
export const ChoosingASizeAndOrientationRewritesTheHeader: Story = {
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: A4, portrait");
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Page size" }), "A3");
    await expect(text(canvasElement).textContent).toBe("@layout document A3\n\n@heading Hello\n");
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Orientation" }), "landscape");
    await expect(text(canvasElement).textContent).toBe("@layout document landscape A3\n\n@heading Hello\n");
    await expect(within(canvasElement).getByRole("button", { name: "Page setup: A3, landscape" })).toBeInTheDocument();
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Page size" }), "A4");
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Orientation" }), "portrait");
    await expect(text(canvasElement).textContent).toBe("@layout document\n\n@heading Hello\n");
  },
};

/** Margins and mirroring are written on the header line, and an emptied side is dropped again. */
export const MarginsAndMirroringAreWrittenOnTheHeader: Story = {
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: A4, portrait");
    await userEvent.type(dialog.getByRole("spinbutton", { name: "Top" }), "2");
    await userEvent.type(dialog.getByRole("spinbutton", { name: "Gutter" }), "1");
    await userEvent.click(dialog.getByRole("checkbox", { name: "Mirror margins" }));
    await expect(text(canvasElement).textContent).toBe("@layout document mirror margins top=2 gutter=1\n\n@heading Hello\n");
    await expect(dialog.getByRole("spinbutton", { name: "Left (inner)" })).toBeInTheDocument();
    await userEvent.clear(dialog.getByRole("spinbutton", { name: "Top" }));
    await userEvent.clear(dialog.getByRole("spinbutton", { name: "Gutter" }));
    await userEvent.click(dialog.getByRole("checkbox", { name: "Mirror margins" }));
    await expect(text(canvasElement).textContent).toBe("@layout document\n\n@heading Hello\n");
  },
};

/** A page style is added, named and given its own paper; it is written as a `@pagestyle` line after the header. */
export const AddingAPageStyleWritesAPagestyleLine: Story = {
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: A4, portrait");
    await userEvent.click(dialog.getByRole("button", { name: "Add page style" }));
    const name = dialog.getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Wide tables");
    const group = within(dialog.getByRole("group", { name: "Wide tables" }));
    await userEvent.selectOptions(group.getByRole("combobox", { name: "Page size" }), "A3");
    await userEvent.selectOptions(group.getByRole("combobox", { name: "Orientation" }), "landscape");
    await userEvent.type(group.getByRole("spinbutton", { name: "Left" }), "1");
    await expect(text(canvasElement).textContent).toBe(
      '@layout document\n@pagestyle "Wide tables" landscape A3 margins left=1\n\n@heading Hello\n',
    );
    await userEvent.click(dialog.getByRole("button", { name: "Remove page style Wide tables" }));
    await expect(text(canvasElement).textContent).toBe("@layout document\n\n@heading Hello\n");
  },
};

/** A layout that already names a setup shows it, in either word order, with its page styles. */
export const ReadsTheSetupFromTheHeaderLines: Story = {
  render: () => <Host initial={'@layout document Letter landscape mirror margins top=2\n@pagestyle "Plain"\n'} />,
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: Letter, landscape");
    // The layout's own fields come first, then each page style's.
    await expect(dialog.getAllByRole("combobox", { name: "Page size" })[0]).toHaveValue("Letter");
    await expect(dialog.getAllByRole("spinbutton", { name: "Top" })[0]).toHaveValue(2);
    await expect(dialog.getByRole("group", { name: "Plain" })).toBeInTheDocument();
  },
};

/** A table layout has no pages, so there is nothing to set. */
export const ATableLayoutHasNoPageSetup: Story = {
  render: () => <Host initial={"@layout table\n"} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button", { name: /^Page setup/ })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ReadsTheSetupFromTheHeaderLines, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ReadsTheSetupFromTheHeaderLines, globals: { theme: "dark" } };
