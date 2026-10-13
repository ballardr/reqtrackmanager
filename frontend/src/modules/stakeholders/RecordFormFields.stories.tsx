import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { CheckboxField, DateField, TextAreaField, TextField } from "./RecordFormFields";

const meta: Meta = { title: "Modules/Stakeholders/RecordFormFields" };
export default meta;

type Story = StoryObj;

export const TextFieldIsLabelledAndReportsChanges: Story = {
  render: () => <TextField label="Role" value="" onChange={fn()} />,
  play: async ({ canvasElement }) => {
    await userEvent.type(within(canvasElement).getByLabelText("Role"), "x");
    await expect(within(canvasElement).getByText("Role")).toBeInTheDocument();
  },
};

export const TextFieldAriaLabelOverridesTheVisibleLabel: Story = {
  render: () => <TextField label="Name" ariaLabel="Persona name" value="Ada" onChange={fn()} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByLabelText("Persona name")).toHaveValue("Ada");
  },
};

export const TextAreaShowsItsHint: Story = {
  render: () => <TextAreaField label="Contact" value="" onChange={fn()} hint="Confidential." rows={3} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByLabelText("Contact")).toHaveAttribute("rows", "3");
    await expect(within(canvasElement).getByText("Confidential.")).toBeInTheDocument();
  },
};

export const DateFieldIsLabelledAndReportsChanges: Story = {
  render: () => <DateField label="Retain until" value="" onChange={fn()} hint="Optional." />,
  play: async ({ canvasElement }) => {
    const input = within(canvasElement).getByLabelText("Retain until");
    await expect(input).toHaveAttribute("type", "date");
    await expect(within(canvasElement).getByText("Optional.")).toBeInTheDocument();
  },
};

export const CheckboxFieldReportsToggles: Story = {
  render: () => {
    const onChange = fn();
    return <CheckboxField label="Consent recorded" checked={false} onChange={onChange} hint="Tick once agreed." />;
  },
  play: async ({ canvasElement }) => {
    const box = within(canvasElement).getByLabelText("Consent recorded");
    await expect(box).not.toBeChecked();
    await userEvent.click(box);
    await expect(within(canvasElement).getByText("Tick once agreed.")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...TextAreaShowsItsHint, globals: { theme: "dark" } };
