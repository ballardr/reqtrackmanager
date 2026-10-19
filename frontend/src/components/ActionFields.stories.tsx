import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { ActionFields, type ActionFieldValues } from "./ActionFields";

const TYPES = [{ id: "t1", name: "Review" }, { id: "t2", name: "Test" }];
const BLANK: ActionFieldValues = { title: "", description: "", actionTypeId: "t1", assignee: null, dueDate: "" };

function Harness({ initial = BLANK, disabled, typePlaceholder }: { initial?: ActionFieldValues; disabled?: boolean; typePlaceholder?: string }) {
  const [values, setValues] = useState(initial);
  return (
    <ActionFields
      values={values} onChange={setValues} actionTypes={TYPES} orgUsers={[]} organizationId="org-1" projectId="project-1"
      disabled={disabled} typePlaceholder={typePlaceholder}
    />
  );
}

const meta: Meta<typeof Harness> = { title: "Components/ActionFields", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

export const EditsEveryField: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("Title"), "Confirm the latency budget");
    await userEvent.type(canvas.getByLabelText("Description"), "With the hardware team");
    await userEvent.selectOptions(canvas.getByLabelText("Type"), "Test");
    await expect(canvas.getByLabelText("Title")).toHaveValue("Confirm the latency budget");
    await expect(canvas.getByLabelText("Type")).toHaveValue("t2");
    await expect(canvas.getByLabelText("Due date")).toHaveAttribute("type", "date");
  },
};

export const TypePlaceholderOffersAnEmptyChoice: Story = {
  args: { initial: { ...BLANK, actionTypeId: "" }, typePlaceholder: "Type" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByLabelText("Type")).toHaveValue("");
  },
};

export const DisabledForAnArchivedAction: Story = {
  args: { initial: { ...BLANK, title: "Archived action" }, disabled: true },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByLabelText("Title")).toBeDisabled();
    await expect(within(canvasElement).getByLabelText("Type")).toBeDisabled();
  },
};

export const DarkTheme: Story = { ...EditsEveryField, globals: { theme: "dark" } };
