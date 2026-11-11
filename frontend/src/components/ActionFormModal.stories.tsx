import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import type { ActionTypeDefinition } from "../api/types";
import { ActionFormModal } from "./ActionFormModal";

const TYPES: ActionTypeDefinition[] = [
  { id: "type-review", project_id: "project-1", name: "Review", sort_order: 0 },
  { id: "type-test", project_id: "project-1", name: "Test", sort_order: 1 },
];

/** Opens the form before the project's action types have loaded, then supplies them. */
function LateTypes({ onSave }: { onSave: React.ComponentProps<typeof ActionFormModal>["onSave"] }) {
  const [types, setTypes] = useState<ActionTypeDefinition[]>([]);
  useEffect(() => {
    const timer = setTimeout(() => setTypes(TYPES), 200);
    return () => clearTimeout(timer);
  }, []);
  return <ActionFormModal projectId="project-1" actionTypes={types} orgUsers={[]} onCancel={fn()} onSave={onSave} />;
}

/** The "New action" form: title, type, assignee and due date, then the shared Links, Tags and Components fields. */
const meta: Meta<typeof ActionFormModal> = {
  title: "Components/ActionFormModal",
  component: ActionFormModal,
  args: { projectId: "project-1", actionTypes: TYPES, orgUsers: [], onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof ActionFormModal>;

export const SavingSendsTheFirstTypeByDefault: Story = {
  play: async ({ args }) => {
    const dialog = within(await within(document.body).findByRole("dialog", { name: "New action" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Title" }), "Check the wiring");
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalled());
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Check the wiring", action_type_id: "type-review" }), [], [],
    );
  },
};

/** The types arrive after the form is open: the select shows the first type, so a save must use it. */
export const TypesThatLoadAfterTheFormOpened: Story = {
  render: (args) => <LateTypes onSave={args.onSave} />,
  play: async ({ args }) => {
    const dialog = within(await within(document.body).findByRole("dialog", { name: "New action" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Title" }), "Check the wiring");
    await waitFor(() => expect(dialog.getByRole("button", { name: "Create" })).toBeEnabled());
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ action_type_id: "type-review" }), [], [],
    );
  },
};
