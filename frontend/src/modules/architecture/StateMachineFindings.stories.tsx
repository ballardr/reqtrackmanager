import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { StateMachineFindings } from "./StateMachineFindings";

const meta: Meta<typeof StateMachineFindings> = {
  title: "Modules/Architecture/StateMachineFindings",
  component: StateMachineFindings,
  args: { findings: [], onSelect: fn() },
};
export default meta;

type Story = StoryObj<typeof StateMachineFindings>;

/** With nothing to report the card says so, with both counts at zero. */
export const NoFindings: Story = {
  play: async ({ canvasElement }) => {
    const card = within(canvasElement);
    await expect(card.getByText("No findings.")).toBeInTheDocument();
    await expect(card.getByText("0 errors")).toBeInTheDocument();
    await expect(card.getByText("0 warnings")).toBeInTheDocument();
  },
};

/** Errors and warnings are counted and labelled with their severity; a finding about a state offers its code to select it. */
export const ErrorsAndWarningsAreCountedAndLabelled: Story = {
  args: {
    findings: [
      { severity: "error", code: "no_initial", subject: "", message: "The state machine diagram has no initial state at the top level." },
      { severity: "warning", code: "unreachable", subject: "STE-003", message: "STE-003 cannot be reached from the initial state." },
    ],
  },
  play: async ({ canvasElement, args }) => {
    const card = within(canvasElement);
    await expect(card.getByText("1 error")).toBeInTheDocument();
    await expect(card.getByText("1 warning")).toBeInTheDocument();
    await expect(card.getByText("Error")).toBeInTheDocument();
    await expect(card.getByText("Warning")).toBeInTheDocument();
    // A finding about the diagram as a whole has no state to select.
    await expect(card.getAllByRole("button")).toHaveLength(2);
    await userEvent.click(card.getByRole("button", { name: "STE-003" }));
    await expect(args.onSelect).toHaveBeenCalledWith("STE-003");
  },
};
