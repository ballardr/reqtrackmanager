import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type ComponentProps } from "react";
import { expect, userEvent, within } from "storybook/test";

import type { StorageUnit } from "../utils/storageLimit";
import { StorageLimitField } from "./StorageLimitField";

/** Holds the typed amount and unit, as the form around the field would. */
function Controlled(args: ComponentProps<typeof StorageLimitField>) {
  const [amount, setAmount] = useState(args.amount);
  const [unit, setUnit] = useState<StorageUnit>(args.unit);
  return <StorageLimitField {...args} amount={amount} unit={unit} onAmountChange={setAmount} onUnitChange={setUnit} />;
}

/** A storage amount entered as a number and a unit (MB or GB). */
const meta: Meta<typeof StorageLimitField> = {
  title: "Components/StorageLimitField",
  component: StorageLimitField,
  args: { label: "Storage limit", help: "How much this may use.", placeholder: "No limit", amount: "", unit: "GB" },
  render: (args) => <Controlled {...args} />,
};
export default meta;

type Story = StoryObj<typeof StorageLimitField>;

/** The placeholder says what an empty amount means; typing and choosing a unit update the field. */
export const TypeAnAmountAndChooseAUnit: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const amount = canvas.getByRole("spinbutton", { name: "Storage limit" });
    await expect(amount).toHaveAttribute("placeholder", "No limit");
    await userEvent.type(amount, "512");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Storage limit unit" }), "MB");
    await expect(amount).toHaveValue(512);
    await expect(canvas.getByRole("combobox", { name: "Storage limit unit" })).toHaveValue("MB");
  },
};

/** A read-only field cannot be changed. */
export const Disabled: Story = {
  args: { amount: "2", disabled: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("spinbutton", { name: "Storage limit" })).toBeDisabled();
    await expect(canvas.getByRole("combobox", { name: "Storage limit unit" })).toBeDisabled();
  },
};
