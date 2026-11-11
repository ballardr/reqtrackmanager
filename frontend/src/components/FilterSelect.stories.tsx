import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { FilterSelect } from "./FilterSelect";

const meta: Meta<typeof FilterSelect> = {
  title: "Components/FilterSelect",
  component: FilterSelect,
  args: {
    label: "Status",
    value: "",
    allLabel: "All statuses",
    onChange: fn(),
    options: [
      { value: "draft", label: "Draft" },
      { value: "approved", label: "Approved" },
    ],
  },
  decorators: [
    (Story) => (
      <div style={{ width: 260 }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;

type Story = StoryObj<typeof FilterSelect>;

export const ChoosingCallsOnChange: Story = {
  play: async ({ canvasElement, args }) => {
    const select = within(canvasElement).getByLabelText("Status");
    await userEvent.selectOptions(select, "approved");
    await expect(args.onChange).toHaveBeenCalledWith("approved");
  },
};

export const AllEntryClearsTheFilter: Story = {
  args: { value: "draft" },
  play: async ({ canvasElement, args }) => {
    const select = within(canvasElement).getByLabelText("Status");
    await userEvent.selectOptions(select, "");
    await expect(args.onChange).toHaveBeenCalledWith("");
  },
};

/** With help the caption and select are siblings, so the select still has its accessible name. */
export const WithHelp: Story = {
  args: { help: "Draft: not yet reviewed.\nApproved: reviewed and accepted." },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Status")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Help: Status" })).toBeInTheDocument();
  },
};

export const WithoutAllEntry: Story = {
  args: { allLabel: undefined, value: "draft" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getAllByRole("option")).toHaveLength(2);
  },
};

export const DisabledUntilParentChosen: Story = {
  args: { label: "Version", disabled: true, allLabel: "All versions" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByLabelText("Version")).toBeDisabled();
  },
};
