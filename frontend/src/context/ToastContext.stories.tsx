import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { withToast } from "../testing/storybook-helpers";
import { useToast } from "./ToastContext";

const onUndo = fn();

function Harness() {
  const { showToast } = useToast();
  return (
    <div className="row">
      <button className="btn" onClick={() => showToast("Requirement archived")}>
        Trigger success
      </button>
      <button className="btn" onClick={() => showToast("Could not save changes.", "error")}>
        Trigger error
      </button>
      <button className="btn" onClick={() => showToast("Inserted Cover", "success", { action: { label: "Undo insertion", onClick: onUndo } })}>
        Trigger undo
      </button>
      <button
        className="btn"
        onClick={() => showToast("Inserted Logo", "success", { details: ['Added page style "Cover".', "The layout already had 1 problem."] })}
      >
        Trigger details
      </button>
    </div>
  );
}

const meta: Meta<typeof Harness> = {
  title: "Components/Toast",
  component: Harness,
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const SuccessToast: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Trigger success" }));
    const body = within(document.body);
    await expect(body.getByText("Requirement archived")).toBeInTheDocument();
    await expect(body.getByRole("status")).toBeInTheDocument();
  },
};

export const ErrorToast: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Trigger error" }));
    const body = within(document.body);
    await expect(body.getByText("Could not save changes.")).toBeInTheDocument();
  },
};

/** Multiple toasts stack rather than replacing each other. */
export const StacksMultipleToasts: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Trigger success" }));
    await userEvent.click(canvas.getByRole("button", { name: "Trigger error" }));
    const body = within(document.body);
    await expect(body.getByText("Requirement archived")).toBeInTheDocument();
    await expect(body.getByText("Could not save changes.")).toBeInTheDocument();
  },
};

export const DismissesManually: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Trigger success" }));
    const body = within(document.body);
    await expect(body.getByText("Requirement archived")).toBeInTheDocument();
    await userEvent.click(body.getByRole("button", { name: "Dismiss notification" }));
    await waitFor(() => expect(body.queryByText("Requirement archived")).not.toBeInTheDocument());
  },
};

/** The action runs its handler and dismisses the toast. */
export const ActionRunsAndDismisses: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Trigger undo" }));
    const body = within(document.body);
    await userEvent.click(await body.findByRole("button", { name: "Undo insertion" }));
    await expect(onUndo).toHaveBeenCalled();
    await waitFor(() => expect(body.queryByText("Inserted Cover")).not.toBeInTheDocument());
  },
};

/** A toast with details lists them and stays past the usual timeout. */
export const DetailsAreListedAndStayUntilDismissed: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Trigger details" }));
    const body = within(document.body);
    await expect(await body.findByText('Added page style "Cover".')).toBeInTheDocument();
    await expect(body.getByText("The layout already had 1 problem.")).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 4500));
    await expect(body.getByText("Inserted Logo")).toBeInTheDocument();
    await userEvent.click(body.getByRole("button", { name: "Dismiss notification" }));
    await waitFor(() => expect(body.queryByText("Inserted Logo")).not.toBeInTheDocument());
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
