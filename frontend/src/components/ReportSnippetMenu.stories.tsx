import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, within } from "storybook/test";

import { ReportSnippetMenu } from "./ReportSnippetMenu";

/** The designer toolbar's single snippet control: an icon button opening Insert snippet and Save as snippet. */
const meta: Meta<typeof ReportSnippetMenu> = {
  title: "Components/ReportSnippetMenu",
  component: ReportSnippetMenu,
  args: { onInsert: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof ReportSnippetMenu>;

export const OneIconButtonOpensBothActions: Story = {
  play: async ({ canvasElement, args }) => {
    const button = within(canvasElement).getByRole("button", { name: "Snippets" });
    await expect(button).toHaveAttribute("title", "Snippets");
    await userEvent.click(button);
    await expect(await screen.findByRole("menuitem", { name: "Save as snippet" })).toBeEnabled();
    await userEvent.click(screen.getByRole("menuitem", { name: "Insert snippet" }));
    await expect(args.onInsert).toHaveBeenCalledTimes(1);
    await expect(args.onSave).not.toHaveBeenCalled();
  },
};

export const SaveIsGreyedOutWithItsReason: Story = {
  args: { saveDisabledReason: "Select a block first: it is saved with everything inside it." },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Snippets" }));
    const save = await screen.findByRole("menuitem", { name: "Save as snippet" });
    await expect(save).toBeDisabled();
    await expect(save).toHaveAttribute("title", "Select a block first: it is saved with everything inside it.");
    await userEvent.click(save);
    await expect(args.onSave).not.toHaveBeenCalled();
  },
};

export const WithNoActionsNothingIsDrawn: Story = {
  args: { onInsert: undefined, onSave: undefined },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button", { name: "Snippets" })).not.toBeInTheDocument();
  },
};
