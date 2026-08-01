import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, within } from "storybook/test";

import type { CustomFieldDefinition } from "../api/types";
import { CustomFieldsForm } from "./CustomFieldsForm";

const definitions: CustomFieldDefinition[] = [
  {
    id: "priority", project_id: "p1", entity_kind: "requirement",
    name: "Priority", field_type: "short_text", options: null, required: true, sort_order: 0,
  },
  {
    id: "notes", project_id: "p1", entity_kind: "requirement",
    name: "Notes", field_type: "long_text", options: null, required: false, sort_order: 1,
  },
  {
    id: "verified", project_id: "p1", entity_kind: "requirement",
    name: "Verified", field_type: "checkbox", options: null, required: false, sort_order: 2,
  },
  {
    id: "risk", project_id: "p1", entity_kind: "requirement",
    name: "Risk level", field_type: "list", options: ["Low", "Medium", "High"], required: false, sort_order: 3,
  },
];

/** Wraps the form in local state so stories/play functions can interact
 * with it like a real controlled form, matching how RequirementsPage and
 * RequirementDetailPage actually use it. */
function Interactive({ disabled }: { disabled?: boolean }) {
  const [values, setValues] = useState<Record<string, unknown>>({ priority: "High" });
  return (
    <CustomFieldsForm
      definitions={definitions}
      values={values}
      disabled={disabled}
      onChange={(fieldId, value) => setValues((v) => ({ ...v, [fieldId]: value }))}
    />
  );
}

const meta: Meta<typeof Interactive> = {
  title: "Components/CustomFieldsForm",
  component: Interactive,
};
export default meta;

type Story = StoryObj<typeof Interactive>;

export const AllFieldTypes: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText(/Priority/)).toHaveValue("High");
    await expect(canvas.getByLabelText(/Notes/)).toBeInTheDocument();
    await expect(canvas.getByLabelText(/Verified/)).not.toBeChecked();
    await expect(canvas.getByLabelText(/Risk level/)).toBeInTheDocument();
  },
};

export const Disabled: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText(/Priority/)).toBeDisabled();
  },
};

export const NoDefinitions: Story = {
  render: () => <CustomFieldsForm definitions={[]} values={{}} onChange={() => {}} />,
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
