import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { RecordLifecycleControls } from "./RecordLifecycleControls";

const meta: Meta<typeof RecordLifecycleControls> = {
  title: "Components/RecordLifecycleControls",
  component: RecordLifecycleControls,
  args: {
    noun: "Persona", status: "draft",
    activateBody: "An Active persona is offered when scoring.", retireBody: "A Retired persona keeps its history.",
    onTransition: fn(async () => undefined),
  },
};
export default meta;

type Story = StoryObj<typeof RecordLifecycleControls>;

const dialog = (name: string) => within(within(document.body).getByRole("dialog", { name }));

export const DraftOffersActivateAndRetire: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Activate" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Retire" })).toBeInTheDocument();
  },
};

export const ActiveOffersOnlyRetire: Story = {
  args: { status: "active" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Activate" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Retire" })).toBeInTheDocument();
  },
};

export const RetiredOffersReactivate: Story = {
  args: { status: "retired" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Reactivate" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
  },
};

export const ActivateConfirmsWithAnOptionalComment: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Activate" }));
    const d = dialog("Activate this Persona?");
    await expect(d.getByText("An Active persona is offered when scoring.")).toBeInTheDocument();
    await userEvent.type(d.getByLabelText("Transition comment"), "Ready");
    await userEvent.click(d.getByRole("button", { name: "Activate" }));
    await waitFor(() => expect(args.onTransition).toHaveBeenCalledWith("activate", "Ready"));
  },
};

export const CancelDoesNothing: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Retire" }));
    await userEvent.click(dialog("Retire this Persona?").getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
    await expect(args.onTransition).not.toHaveBeenCalled();
  },
};

export const DarkTheme: Story = { ...DraftOffersActivateAndRetire, globals: { theme: "dark" } };
