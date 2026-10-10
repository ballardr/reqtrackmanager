import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { withToast } from "../testing/storybook-helpers";
import { SupersedeAction } from "./SupersedeAction";

/** The page-supplied "Supersede another …" control shown beside the Links panel's "Add link". */
const meta: Meta<typeof SupersedeAction> = {
  title: "Components/SupersedeAction",
  component: SupersedeAction,
  decorators: [withToast()],
  args: {
    artefactLabel: "Strategy",
    loadCandidates: fn(async () => [{ id: "s-1", label: "Go to market 2025" }, { id: "s-2", label: "Platform first" }]),
    onSupersede: fn(async () => undefined),
    onDone: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof SupersedeAction>;

export const SupersedesTheChosenRecord: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Supersede another Strategy" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    const confirm = dialog.getByRole("button", { name: "Supersede" });
    await expect(confirm).toBeDisabled();
    await userEvent.selectOptions(await dialog.findByLabelText("Strategy"), "s-2");
    await userEvent.click(confirm);
    await waitFor(() => expect(args.onSupersede).toHaveBeenCalledWith("s-2"));
    await waitFor(() => expect(args.onDone).toHaveBeenCalled());
  },
};

export const SaysSoWhenThereIsNothingToSupersede: Story = {
  args: { loadCandidates: fn(async () => []) },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Supersede another Strategy" }));
    await expect(await within(document.body).findByText("Nothing to supersede.")).toBeInTheDocument();
  },
};

export const ShowsTheServersReasonWhenItRefuses: Story = {
  args: { onSupersede: fn(async () => { throw new Error("That Strategy is already superseded."); }) },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Supersede another Strategy" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.selectOptions(await dialog.findByLabelText("Strategy"), "s-1");
    await userEvent.click(dialog.getByRole("button", { name: "Supersede" }));
    await expect(await within(document.body).findByText("That Strategy is already superseded.")).toBeInTheDocument();
  },
};
