import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildDiagram, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
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
