import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

import type { OrgUser, ProjectStage } from "../api/types";
import { FormGrid } from "./FormGrid";
import { RequirementFields } from "./RequirementFields";
import { EMPTY_REQUIREMENT_FIELDS, type RequirementFieldValues } from "./requirementFieldValues";

const users: OrgUser[] = [
  {
    user_id: "u1", email: "alex.morgan@example.com", display_name: "Alex Morgan", is_active: true,
    is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];
const stages = [
  { id: "stage-1", project_id: "p", name: "Release 1", status: "planned", sort_order: 0, is_current: true, approved_at: null, completed_at: null },
  { id: "stage-2", project_id: "p", name: "Release 2", status: "planned", sort_order: 1, is_current: false, approved_at: null, completed_at: null },
] as unknown as ProjectStage[];

/** Holds the values the way a page does, so typing in a story behaves like the real forms. */
function Harness({ initial }: { initial: RequirementFieldValues }) {
  const [values, setValues] = useState(initial);
  return (
    <FormGrid minColumn="18rem">
      <RequirementFields
        values={values} onChange={setValues} stages={stages} orgUsers={users}
        ownerPlaceholder="Defaults to you" afterDescription={<p data-testid="page-fields">Page-specific fields</p>}
      />
      <output data-testid="values">{JSON.stringify(values)}</output>
    </FormGrid>
  );
}

const meta: Meta<typeof Harness> = {
  title: "Components/RequirementFields",
  component: Harness,
  args: { initial: { ...EMPTY_REQUIREMENT_FIELDS, targetStageId: "stage-1" } },
};
export default meta;

type Story = StoryObj<typeof Harness>;

/** The create dialog and the edit form show the same fields: everything the edit form edits is here. */
export const EveryEditableField: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const label of ["Name", "Reasoning", "Clarification", "Description", "Review date", "Assigned reviewer", "Owner"]) {
      await expect(canvas.getAllByText(label, { exact: false }).length).toBeGreaterThan(0);
    }
    await expect(canvas.getByTestId("page-fields")).toBeInTheDocument();
    await expect(canvas.getByLabelText(/Reminder lead time/)).toBeInTheDocument();
  },
};

/** Typing updates the shared value set (clarification and review fields included). */
export const EditsClarificationAndReviewFields: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("Clarification"), "Applies to field staff");
    await userEvent.type(canvas.getByLabelText(/Reminder lead time/), "14");
    const values = JSON.parse(canvas.getByTestId("values").textContent ?? "{}");
    await expect(values.clarification).toBe("Applies to field staff");
    await expect(values.reviewLeadDays).toBe("14");
  },
};

export const DarkTheme: Story = { ...EveryEditableField, globals: { theme: "dark" } };
