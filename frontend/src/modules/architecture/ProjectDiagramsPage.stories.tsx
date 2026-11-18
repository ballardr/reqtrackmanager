import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildDiagram, buildElement, buildFolder, buildStateMachine, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { ProjectDiagramsPage } from "./ProjectDiagramsPage";

const DIAGRAMS = [
  buildDiagram(),
  buildDiagram({ id: "dgm-2", unique_code: "DGM-002", name: "Gateway internals", scope_element_id: "el-1", scope_element_code: "ELM-001", scope_element_name: "Gateway" }),
  buildDiagram({ id: "dgm-3", unique_code: "DGM-003", name: "Old layout", status: "retired" }),
];

const meta: Meta<typeof ProjectDiagramsPage> = {
  title: "Modules/Architecture/ProjectDiagramsPage",
  component: ProjectDiagramsPage,
  decorators: [
    withAuth(buildUser({ id: "user-1" })),
    withRouter(`/projects/${PROJECT_ID}/modules/architecture/diagrams`, "/projects/:projectId/modules/architecture/diagrams"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectDiagramsPage>;

export const ListShowsScopeAndHidesRetiredByDefault: Story = {
  beforeEach: () => { mockArchitectureReads({ diagrams: DIAGRAMS }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Diagrams" });
    const system = within(within(table).getByRole("link", { name: "DGM-001" }).closest("tr")!);
    await expect(system.getByText("System context")).toBeInTheDocument();
    await expect(system.getByRole("button", { name: "Help: System context" })).toBeInTheDocument();
    const inside = within(within(table).getByRole("link", { name: "DGM-002" }).closest("tr")!);
    await expect(inside.getByText("ELM-001 Gateway")).toBeInTheDocument();
    await expect(within(table).queryByRole("link", { name: "DGM-003" })).not.toBeInTheDocument();
  },
};

export const NewDiagramPostsTheForm: Story = {
  beforeEach: () => {
    mockArchitectureReads({ diagrams: DIAGRAMS });
    spyOn(api, "post").mockResolvedValue(buildDiagram({ id: "dgm-new" }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "New diagram" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.type(await dialog.findByLabelText(/^Name/), "Context");
    await userEvent.click(dialog.getByRole("checkbox", { name: "Place the scope's elements" }));
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/architecture/diagrams`,
      expect.objectContaining({ name: "Context", scope_element_id: null, populate: true, activate: false, connection_detail: false }),
    ));
  },
};

/** The Contents header orders the diagrams by their count of boxes, a number, not text. */
export const BoxCountHeaderSortsTheList: Story = {
  beforeEach: () => {
    mockArchitectureReads({ diagrams: [buildDiagram({ placement_count: 10 }), buildDiagram({ id: "dgm-2", unique_code: "DGM-002", name: "Small", placement_count: 9 })] });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Diagrams" });
    await userEvent.click(within(table).getByRole("button", { name: "Contents" }));
    await waitFor(() => expect(within(table).getAllByRole("link").map((link) => link.textContent)).toEqual(["DGM-002", "DGM-001"]));
    await expect(within(table).getByRole("columnheader", { name: "Contents" })).toHaveAttribute("aria-sort", "ascending");
  },
};

/** The Folder column shows each diagram's path, and choosing a folder in the filter panel narrows the list to it. */
export const FolderColumnAndFilterNarrowTheList: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      diagrams: [
        buildDiagram({ folder_id: "df-1", folder_path: "Overviews" }),
        buildDiagram({ id: "dgm-2", unique_code: "DGM-002", name: "Loose", folder_id: null, folder_path: null }),
      ],
      folders: [buildFolder({ id: "df-1", kind: "diagram", name: "Overviews", path: "Overviews", record_count: 1 })],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Diagrams" });
    await expect(within(within(table).getByRole("link", { name: "DGM-001" }).closest("tr")!).getByText("Overviews")).toBeInTheDocument();
    await userEvent.click(await canvas.findByRole("button", { name: "Folder Overviews" }));
    await waitFor(() => expect(within(table).queryByRole("link", { name: "DGM-002" })).not.toBeInTheDocument());
    await expect(within(table).getByRole("link", { name: "DGM-001" })).toBeInTheDocument();
  },
};

const MACHINES = [
  buildStateMachine({ error_count: 1, warning_count: 2 }),
  buildStateMachine({ id: "smd-2", unique_code: "SMD-002", name: "Gateway faults", status: "active", state_count: 1 }),
];

/** Block diagrams and state machine diagrams are one list: a Type column, the element and the count of states or elements. */
export const BothTypesAreOneListWithATypeColumn: Story = {
  beforeEach: () => { mockArchitectureReads({ diagrams: DIAGRAMS, stateMachines: MACHINES }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Diagrams" });
    const machine = within(within(table).getByRole("link", { name: "SMD-001" }).closest("tr")!);
    await expect(machine.getByText("State machine diagram")).toBeInTheDocument();
    await expect(machine.getByText("ELM-001 Gateway")).toBeInTheDocument();
    await expect(machine.getByText("4 states")).toBeInTheDocument();
    await expect(machine.getByText("1 error")).toBeInTheDocument();
    await expect(machine.getByText("2 warnings")).toBeInTheDocument();
    await expect(within(within(table).getByRole("link", { name: "SMD-001" })).getByText("SMD-001")).toHaveAttribute("href", expect.stringContaining("/state-machine-diagrams/smd-1"));
    await expect(within(within(table).getByRole("link", { name: "DGM-001" }).closest("tr")!).getByText("Block diagram")).toBeInTheDocument();
  },
};

/** The Type filter keeps one type's rows. */
export const TypeFilterNarrowsToOneType: Story = {
  beforeEach: () => { mockArchitectureReads({ diagrams: DIAGRAMS, stateMachines: MACHINES }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Diagrams" });
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Type" }), "state_machine");
    await waitFor(() => expect(within(table).queryByRole("link", { name: "DGM-001" })).not.toBeInTheDocument());
    await expect(within(table).getByRole("link", { name: "SMD-001" })).toBeInTheDocument();
  },
};

/** A person who cannot read state machine diagrams sees the tab as before: no Type column, filter or Type choice. */
export const ATypeThePersonCannotReadIsLeftOut: Story = {
  beforeEach: () => { mockArchitectureReads({ diagrams: DIAGRAMS, stateMachinesRefused: true }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Diagrams" });
    await expect(within(table).queryByRole("columnheader", { name: "Type" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("combobox", { name: "Type" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "New diagram" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await expect(dialog.queryByRole("combobox", { name: "Type" })).not.toBeInTheDocument();
  },
};

/** New diagram starts with the Type: choosing State machine diagram asks for the element it describes and creates that type. */
export const NewStateMachineDiagramPostsItsOwnForm: Story = {
  beforeEach: () => {
    mockArchitectureReads({ diagrams: DIAGRAMS, stateMachines: MACHINES, elements: [buildElement()] });
    spyOn(api, "post").mockResolvedValue(buildStateMachine({ id: "smd-new" }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "New diagram" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.selectOptions(await dialog.findByRole("combobox", { name: "Type" }), "state_machine");
    // The block diagram's fields are replaced by the state machine diagram's, and it cannot be activated before it has states.
    await expect(dialog.queryByLabelText("Scope element")).not.toBeInTheDocument();
    await expect(dialog.queryByRole("button", { name: "Save and activate" })).not.toBeInTheDocument();
    await userEvent.type(dialog.getByLabelText(/^Name/), "Modes");
    await expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.selectOptions(dialog.getByLabelText(/^Element/), "el-1");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/architecture/state-machine-diagrams`,
      expect.objectContaining({ name: "Modes", element_id: "el-1", activate: false }),
    ));
  },
};
