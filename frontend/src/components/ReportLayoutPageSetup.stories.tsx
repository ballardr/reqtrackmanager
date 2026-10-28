import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, screen, userEvent, within } from "storybook/test";

import { ReportLayoutPageSetup } from "./ReportLayoutPageSetup";

/** Hosts the control with the text it edits, and shows the text so a story can read the rewritten first line. */
function Host({ initial }: { initial: string }) {
  const [text, setText] = useState(initial);
  return (
    <div className="stack">
      <ReportLayoutPageSetup text={text} onChange={setText} />
      <pre aria-label="Text">{text}</pre>
    </div>
  );
}

/** Page orientation and size, written into the layout text's first line. */
const meta: Meta<typeof ReportLayoutPageSetup> = {
  title: "Components/ReportLayoutPageSetup",
  component: ReportLayoutPageSetup,
  render: () => <Host initial={"@layout document\n\n@heading Hello\n"} />,
};
export default meta;

type Story = StoryObj<typeof ReportLayoutPageSetup>;

const text = (canvasElement: HTMLElement) => within(canvasElement).getByLabelText("Text");

/** The button says the current setup, and a change rewrites only the first line. */
export const ChoosingASizeAndOrientationRewritesTheHeader: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Page setup: A4, portrait" }));
    const popover = within(await screen.findByRole("dialog", { name: "Page setup" }));
    await userEvent.selectOptions(popover.getByRole("combobox", { name: "Page size" }), "A3");
    await expect(text(canvasElement).textContent).toBe("@layout document A3\n\n@heading Hello\n");
    await userEvent.selectOptions(popover.getByRole("combobox", { name: "Orientation" }), "landscape");
    await expect(text(canvasElement).textContent).toBe("@layout document landscape A3\n\n@heading Hello\n");
    await expect(canvas.getByRole("button", { name: "Page setup: A3, landscape" })).toBeInTheDocument();
    await userEvent.selectOptions(popover.getByRole("combobox", { name: "Page size" }), "A4");
    await userEvent.selectOptions(popover.getByRole("combobox", { name: "Orientation" }), "portrait");
    await expect(text(canvasElement).textContent).toBe("@layout document\n\n@heading Hello\n");
  },
};

/** A layout that already names a setup shows it, in either word order. */
export const ReadsTheSetupFromTheFirstLine: Story = {
  render: () => <Host initial={"@layout document Letter landscape\n"} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Page setup: Letter, landscape" })).toBeInTheDocument();
  },
};

/** A table layout has no pages, so there is nothing to set. */
export const ATableLayoutHasNoPageSetup: Story = {
  render: () => <Host initial={"@layout table\n"} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button", { name: /^Page setup/ })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ReadsTheSetupFromTheFirstLine, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ReadsTheSetupFromTheFirstLine, globals: { theme: "dark" } };
