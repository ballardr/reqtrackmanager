import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { withToast } from "../testing/storybook-helpers";
import { useToast } from "./ToastContext";

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

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
