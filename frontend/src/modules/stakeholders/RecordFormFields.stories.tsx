import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { TextAreaField, TextField } from "./RecordFormFields";

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

export const DarkTheme: Story = { ...TextAreaShowsItsHint, globals: { theme: "dark" } };
