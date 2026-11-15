import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildElement, buildStateMachine, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { NewStateMachineDiagramButton } from "./NewStateMachineDiagramButton";

const ELEMENT = buildElement();

const meta: Meta<typeof NewStateMachineDiagramButton> = {
  title: "Modules/Architecture/NewStateMachineDiagramButton",
  component: NewStateMachineDiagramButton,
  args: { projectId: PROJECT_ID, element: ELEMENT, candidates: [ELEMENT] },
  decorators: [withAuth(buildUser({ id: "user-1" })), withRouter(`/projects/${PROJECT_ID}/modules/architecture/elements/el-1`), withToast()],
};
export default meta;

type Story = StoryObj<typeof NewStateMachineDiagramButton>;

/** The button opens the shared form for a state machine diagram with this element chosen and no Type choice, and posts it. */
export const PreselectsTheElementAndPostsTheDiagram: Story = {
  beforeEach: () => {
    mockArchitectureReads();
    spyOn(api, "post").mockResolvedValue(buildStateMachine({ id: "smd-new" }) as never);
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "New state machine diagram" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(dialog.queryByRole("combobox", { name: "Type" })).not.toBeInTheDocument();
    await expect(dialog.getByLabelText(/^Element/)).toHaveValue("el-1");
    await userEvent.type(dialog.getByLabelText(/^Name/), "Modes");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/architecture/state-machine-diagrams`,
      expect.objectContaining({ name: "Modes", element_id: "el-1", activate: false }),
    ));
  },
};

/** A project with the state machine sub-component switched off has no button, since the create would be refused. */
export const IsAbsentWhenStateMachineDiagramsAreSwitchedOff: Story = {
  beforeEach: () => { mockArchitectureReads({ disabledSubComponents: ["architecture_state_machine"] }); },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining("/enabled-modules")));
    await new Promise((resolve) => setTimeout(resolve, 50));
    await expect(within(canvasElement).queryByRole("button", { name: "New state machine diagram" })).not.toBeInTheDocument();
  },
};
