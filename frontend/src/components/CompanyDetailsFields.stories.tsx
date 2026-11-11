import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { CompanyDetailsFields } from "./CompanyDetailsFields";
import { TextField } from "./FormFields";

const help = { companyName: "The company name.", website: "The website.", address: "The postal address." };

const meta: Meta<typeof CompanyDetailsFields> = {
  title: "Components/CompanyDetailsFields",
  component: CompanyDetailsFields,
  args: {
    value: { companyName: "", website: "", address: "" }, onChange: fn(), help,
    placeholders: { companyName: "Platform Co", website: "https://platform.example.com", address: "1 Platform Way" },
  },
  render: (args) => <div style={{ width: 640 }}><CompanyDetailsFields {...args} /></div>,
};
export default meta;

type Story = StoryObj<typeof CompanyDetailsFields>;

/** An empty field shows the value it falls back to as its placeholder, and typing reports the field and its text. */
export const PlaceholdersAndEditing: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Company name")).toHaveAttribute("placeholder", "Platform Co");
    await expect(canvas.getByLabelText("Website")).toHaveAttribute("placeholder", "https://platform.example.com");
    await expect(canvas.getByLabelText("Postal address")).toHaveAttribute("placeholder", "1 Platform Way");
    await userEvent.type(canvas.getByLabelText("Website"), "x");
    await expect(args.onChange).toHaveBeenCalledWith("website", "x");
  },
};

/** The platform tier adds its prefix before the company name and its identifier after the address. */
export const WithLeadingAndTrailingFields: Story = {
  args: {
    leading: <TextField helpNotNeeded label="Prefix" value="" onChange={fn()} />,
    trailing: <TextField helpNotNeeded label="Company identifier" value="" onChange={fn()} />,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const labels = Array.from(canvasElement.querySelectorAll("label")).map((l) => l.textContent?.replace(/\s*\(\?\)\s*$/, "").trim());
    await expect(labels[0]).toBe("Prefix");
    await expect(labels[labels.length - 1]).toBe("Company identifier");
    await expect(canvas.getByLabelText("Company name")).toBeInTheDocument();
  },
};
