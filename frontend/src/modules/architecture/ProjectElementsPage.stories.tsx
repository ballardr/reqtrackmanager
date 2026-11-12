import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildElement, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { ProjectElementsPage } from "./ProjectElementsPage";

const ELEMENTS = [
  buildElement(),
  buildElement({ id: "el-2", unique_code: "ELM-002", name: "Orders", element_type_id: "et-1", parent_id: "el-1", ports: [] }),
  buildElement({ id: "el-3", unique_code: "ELM-003", name: "Legacy bus", status: "retired", ports: [] }),
];

const meta: Meta<typeof ProjectElementsPage> = {
  title: "Modules/Architecture/ProjectElementsPage",
  component: ProjectElementsPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    (Story, context) =>
      withRouter(
        `/projects/${PROJECT_ID}/modules/architecture/elements${context.parameters.query ?? ""}`,
        "/projects/:projectId/modules/architecture/elements",
      )(Story, context),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectElementsPage>;

export const ListShowsTypeParentAndStatusAndHidesRetiredByDefault: Story = {
  beforeEach: () => { mockArchitectureReads({ elements: ELEMENTS }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Elements" });
    const row = within(within(table).getByRole("link", { name: "ELM-002" }).closest("tr")!);
    await expect(row.getByText("Orders")).toBeInTheDocument();
    await expect(row.getByText("Service")).toBeInTheDocument();
    await expect(row.getByText("Gateway")).toBeInTheDocument();
    await expect(within(table).getByRole("link", { name: "ELM-001" })).toHaveAttribute(
      "href", `/projects/${PROJECT_ID}/modules/architecture/elements/el-1`,
    );
    await expect(canvas.getByRole("checkbox", { name: "Open only" })).toBeChecked();
    await expect(canvas.queryByRole("link", { name: "ELM-003" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("checkbox", { name: "Open only" }));
    await expect(await canvas.findByRole("link", { name: "ELM-003" })).toBeInTheDocument();
  },
};

/** An element shared by another owner is listed, marked Shared. */
export const SharedElementsAreMarked: Story = {
  beforeEach: () => {
    mockArchitectureReads({
      elements: [buildElement()],
      shared: [buildElement({ id: "el-9", project_id: "project-2", shared: true, unique_code: "ELM-009", name: "Identity provider" })],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const row = within((await canvas.findByRole("link", { name: "ELM-009" })).closest("tr")!);
    await expect(row.getByText("Shared")).toBeInTheDocument();
  },
};

/** The tree arranges elements under their parents. */
export const TreeNestsChildrenUnderTheirParent: Story = {
  parameters: { query: "?view=tree" },
  beforeEach: () => { mockArchitectureReads({ elements: ELEMENTS }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const tree = await canvas.findByRole("tree").catch(() => null);
    const parent = await canvas.findByRole("link", { name: /ELM-001 Gateway/ });
    await expect(parent).toBeInTheDocument();
    const child = await canvas.findByRole("link", { name: /ELM-002 Orders/ });
    await expect(parent.closest("li")!.contains(child)).toBe(true);
    await expect(tree === null || tree.contains(child)).toBe(true);
  },
};

export const EmptyProjectSaysSo: Story = {
  beforeEach: () => { mockArchitectureReads({ elements: [] }); },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No elements recorded for this project yet.")).toBeInTheDocument();
  },
};

/** New element opens the shared form; saving posts it with the chosen type. */
export const NewElementPostsTheForm: Story = {
  beforeEach: () => {
    mockArchitectureReads({ elements: ELEMENTS });
    spyOn(api, "post").mockResolvedValue(buildElement({ id: "el-new" }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "New element" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(dialog.getByLabelText("Name"), "Scheduler");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/architecture/elements`,
      expect.objectContaining({ name: "Scheduler", element_type_id: "et-1", activate: false, ports: [] }),
    ));
  },
};
