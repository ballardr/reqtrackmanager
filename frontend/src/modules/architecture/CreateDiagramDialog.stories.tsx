import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withToast } from "../../testing/storybook-helpers";
import { buildDiagram, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { CreateDiagramDialog } from "./CreateDiagramDialog";

const meta: Meta<typeof CreateDiagramDialog> = {
  title: "Modules/Architecture/CreateDiagramDialog",
  component: CreateDiagramDialog,
  args: { projectId: PROJECT_ID, onCreated: fn(), onCancel: fn() },
  decorators: [withAuth(buildUser({ id: "user-1" })), withToast()],
  beforeEach: () => {
    mockArchitectureReads();
    spyOn(api, "post").mockResolvedValue(buildDiagram({ id: "dgm-new" }) as never);
  },
};
export default meta;

type Story = StoryObj<typeof CreateDiagramDialog>;

/** The Links panel's "Create new" opens the same form as the Diagrams list and reports the new id. */
export const CreatesTheDiagramAndReportsItsId: Story = {
  play: async ({ args }) => {
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.type(dialog.getByLabelText(/Name/), "Overview");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onCreated).toHaveBeenCalledWith("dgm-new", "block"));
  },
};

/** Closing the dialog without saving reports the cancel and creates nothing. */
export const CancelCreatesNothing: Story = {
  play: async ({ args }) => {
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.click(dialog.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(args.onCancel).toHaveBeenCalled());
    expect(api.post).not.toHaveBeenCalled();
  },
};
