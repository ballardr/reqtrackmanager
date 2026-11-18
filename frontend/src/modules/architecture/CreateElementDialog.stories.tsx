import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withToast } from "../../testing/storybook-helpers";
import { buildElement, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { CreateElementDialog } from "./CreateElementDialog";

const meta: Meta<typeof CreateElementDialog> = {
  title: "Modules/Architecture/CreateElementDialog",
  component: CreateElementDialog,
  args: { projectId: PROJECT_ID, onCreated: fn(), onCancel: fn() },
  decorators: [withAuth(buildUser({ id: "user-1" })), withToast()],
  beforeEach: () => {
    mockArchitectureReads();
    spyOn(api, "post").mockResolvedValue(buildElement({ id: "el-new" }) as never);
  },
};
export default meta;

type Story = StoryObj<typeof CreateElementDialog>;

/** The Links panel's "Create new" opens the same form and reports the new id. */
export const CreatesTheElementAndReportsItsId: Story = {
  play: async ({ args }) => {
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Name"), "Scheduler");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onCreated).toHaveBeenCalledWith("el-new"));
  },
};
