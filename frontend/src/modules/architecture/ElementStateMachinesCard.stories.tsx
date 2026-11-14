import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildElement, buildStateMachine, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { ElementStateMachinesCard } from "./ElementStateMachinesCard";

const ELEMENT = buildElement();

const meta: Meta<typeof ElementStateMachinesCard> = {
  title: "Modules/Architecture/ElementStateMachinesCard",
  component: ElementStateMachinesCard,
  args: { projectId: PROJECT_ID, element: ELEMENT, candidates: [ELEMENT], readOnly: false },
  decorators: [withAuth(buildUser({ id: "user-1" })), withRouter(`/projects/${PROJECT_ID}/modules/architecture/elements/el-1`), withToast()],
};
export default meta;

type Story = StoryObj<typeof ElementStateMachinesCard>;

/** The card lists the element's state machine diagrams with status and state count, each a link to its editor. */
export const ListsTheElementsStateMachineDiagrams: Story = {
  beforeEach: () => { mockArchitectureReads({ stateMachines: [buildStateMachine(), buildStateMachine({ id: "smd-2", unique_code: "SMD-002", name: "Faults", state_count: 1 })] }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const card = within(await canvas.findByRole("region", { name: "State machine diagrams" }));
    await expect(card.getByRole("link", { name: /SMD-001 Gateway modes/ })).toHaveAttribute("href", expect.stringContaining("/state-machine-diagrams/smd-1"));
    await expect(card.getByText("4 states")).toBeInTheDocument();
    await expect(card.getByText("1 state")).toBeInTheDocument();
  },
};

/** New opens the shared form for a state machine diagram with this element chosen, and no Type choice. */
export const NewPreselectsTheElementAndPostsTheDiagram: Story = {
  beforeEach: () => {
    mockArchitectureReads({ stateMachines: [] });
    spyOn(api, "post").mockResolvedValue(buildStateMachine({ id: "smd-new" }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("No state machine diagrams.")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "New state machine diagram" }));
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

/** A person who cannot read state machine diagrams (the list is refused) sees no card, so the page is as it was. */
export const ThereIsNoCardWithoutAccess: Story = {
  beforeEach: () => { mockArchitectureReads({ stateMachinesRefused: true }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    await expect(canvas.queryByRole("region", { name: "State machine diagrams" })).not.toBeInTheDocument();
  },
};

/** An archived element takes no new diagram. */
export const AnArchivedElementOffersNoNewButton: Story = {
  args: { readOnly: true },
  beforeEach: () => { mockArchitectureReads({ stateMachines: [] }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText("No state machine diagrams.");
    await expect(canvas.queryByRole("button", { name: "New state machine diagram" })).not.toBeInTheDocument();
  },
};
