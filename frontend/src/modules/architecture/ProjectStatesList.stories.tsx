import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, userEvent, waitFor, within } from "storybook/test";

import { buildUser, withAuth, withRouter, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { buildState, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { ProjectStatesList } from "./ProjectStatesList";

const meta: Meta<typeof ProjectStatesList> = {
  title: "Modules/Architecture/ProjectStatesList",
  component: ProjectStatesList,
  args: { viewTabs: null },
  decorators: [
    withAuth(buildUser({ id: "user-1" })),
    withRouter(`/projects/${PROJECT_ID}/modules/architecture/diagrams?view=states`, "/projects/:projectId/modules/architecture/diagrams"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectStatesList>;

const STATES = [
  buildState(),
  buildState({ id: "ste-0", unique_code: "STE-000", name: "Start", kind: "initial" }),
];

/** The list names each state's diagram and kind and links to the diagram with the state selected; the Kind filter narrows it. */
export const ListsEveryStateWithItsDiagram: Story = {
  beforeEach: () => { mockArchitectureReads({ states: STATES }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "States" });
    const row = within(within(table).getByRole("link", { name: "STE-001" }).closest("tr")!);
    await expect(row.getByText("Idle")).toBeInTheDocument();
    await expect(row.getByText("SMD-001 Gateway modes")).toBeInTheDocument();
    await expect(row.getByText("ELM-001 Gateway")).toBeInTheDocument();
    await expect(within(table).getByRole("link", { name: "STE-001" })).toHaveAttribute(
      "href", expect.stringContaining("/state-machine-diagrams/smd-1?state=ste-1"),
    );
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Kind" }), "initial");
    await waitFor(() => expect(within(table).queryByRole("link", { name: "STE-001" })).not.toBeInTheDocument());
    await expect(within(table).getByRole("link", { name: "STE-000" })).toBeInTheDocument();
  },
};

/** A header click orders the list, with the sort in the address. */
export const NameHeaderSortsTheList: Story = {
  beforeEach: () => { mockArchitectureReads({ states: STATES }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "States" });
    await userEvent.click(within(table).getByRole("button", { name: "Name" }));
    await waitFor(() => expect(within(table).getAllByRole("link").map((link) => link.textContent)).toEqual(["STE-001", "STE-000"]));
    await expect(within(table).getByRole("columnheader", { name: "Name" })).toHaveAttribute("aria-sort", "ascending");
  },
};

/** Every optional column is on by default; the column chooser hides one and the reset shows it again. */
export const ColumnChooserHidesAndRestoresAColumn: Story = {
  decorators: [withStatefulAuth(buildUser({ id: "user-1" }))],
  beforeEach: () => { mockArchitectureReads({ states: STATES }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "States" });
    for (const name of ["Code", "Name", "State machine diagram", "Kind", "Element"]) {
      await expect(within(table).getByRole("columnheader", { name })).toBeInTheDocument();
    }
    await userEvent.click(canvas.getByRole("button", { name: "Choose columns" }));
    const dialog = await screen.findByRole("dialog", { name: "Columns" });
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Element" }));
    await expect(within(table).queryByRole("columnheader", { name: "Element" })).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Show the default columns" }));
    await expect(within(table).getByRole("columnheader", { name: "Element" })).toBeInTheDocument();
  },
};
