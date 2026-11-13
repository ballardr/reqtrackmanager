import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildConnection, buildElement, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { ElementDetailPage } from "./ElementDetailPage";

const PARENT = buildElement({ id: "el-0", unique_code: "ELM-000", name: "Platform", ports: [] });
const ELEMENT = buildElement({ parent_id: "el-0", version: 3 });
const CHILD = buildElement({ id: "el-2", unique_code: "ELM-002", name: "Rate limiter", parent_id: "el-1", ports: [] });

const meta: Meta<typeof ElementDetailPage> = {
  title: "Modules/Architecture/ElementDetailPage",
  component: ElementDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1" })),
    (Story, context) =>
      withRouter(
        `/projects/${PROJECT_ID}/modules/architecture/elements/${context.parameters.elementId ?? "el-1"}`,
        "/projects/:projectId/modules/architecture/elements/:elementId",
      )(Story, context),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ElementDetailPage>;

export const ShowsPortsChildrenConnectionsAndSharing: Story = {
  beforeEach: () => {
    const get = mockArchitectureReads({ elements: [PARENT, ELEMENT, CHILD], element: ELEMENT, connections: [buildConnection()] });
    return () => get.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { name: /Gateway/ })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Platform" })).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/architecture/elements/el-0`);
    await expect(canvas.getByLabelText("Port name", { selector: "input:not([placeholder])" })).toHaveValue("HTTPS API");
    await expect(await canvas.findByRole("link", { name: /ELM-002 Rate limiter/ })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: /CON-001 Client traffic/ })).toBeInTheDocument();
    await expect(await canvas.findByText("Shared infrastructure · 1 grant")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Change state" })).toBeInTheDocument();
  },
};

/** An element another owner shares is read-only: no Edit, no state menu, no port controls, no Add child. */
export const SharedElementIsReadOnly: Story = {
  parameters: { elementId: "el-9" },
  beforeEach: () => {
    const shared = buildElement({ id: "el-9", project_id: "project-2", shared: true, unique_code: "ELM-009", name: "Identity provider", ports: [] });
    const get = mockArchitectureReads({ elements: [PARENT], shared: [shared], element: shared, connections: [] });
    return () => get.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { name: /Identity provider/ })).toBeInTheDocument();
    await expect(canvas.getByText("Shared")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Change state" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add child" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add port" })).not.toBeInTheDocument();
    await expect(canvas.getByText(/only its owner changes it/)).toBeInTheDocument();
  },
};

/** The menu offers the moves the server returned for the record's state, named from the current state. */
export const ChangeStateOffersTheServersMoves: Story = {
  beforeEach: () => {
    const draft = buildElement({ status: "draft", version: 3 });
    const get = mockArchitectureReads({ elements: [PARENT, draft], element: draft, connections: [] });
    return () => get.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Change state" }));
    const menu = within(document.body).getByRole("menu", { name: "Change state" });
    await expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent?.trim())).toEqual([
      "Move from Draft to Proposed", "Move from Draft to Active", "Move from Draft to Rejected",
    ]);
  },
};

/** The (?) beside the menu describes every state, not only the current one. */
export const ChangeStateHelpDescribesEveryState: Story = {
  beforeEach: () => {
    const get = mockArchitectureReads({ elements: [PARENT, ELEMENT], element: ELEMENT, connections: [] });
    return () => get.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Help: Change state" }));
    const tip = await within(document.body).findByRole("tooltip");
    for (const state of ["Draft:", "Proposed:", "Active:", "Retired:", "Rejected:"]) await expect(tip).toHaveTextContent(state);
  },
};

/** Moving sends the version the page was based on; a refusal from the server is shown. */
export const MoveSendsTheVersionAndShowsARefusal: Story = {
  beforeEach: () => {
    const get = mockArchitectureReads({ elements: [PARENT, ELEMENT], element: ELEMENT, connections: [] });
    const post = spyOn(api, "post").mockRejectedValue(new Error("Retire or move the active child elements first."));
    return () => { get.mockRestore(); post.mockRestore(); };
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Change state" }));
    await userEvent.click(within(document.body).getByRole("menuitem", { name: "Move from Active to Retired" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/architecture/elements/el-1/status`, { version: 3, status: "retired" },
    ));
    await expect(await within(document.body).findByText("Retire or move the active child elements first.")).toBeInTheDocument();
  },
};

/** Edit sends only the fields that changed, with the version. */
export const EditSendsOnlyTheChangedFields: Story = {
  beforeEach: () => {
    const get = mockArchitectureReads({ elements: [PARENT, ELEMENT], element: ELEMENT, connections: [] });
    const put = spyOn(api, "put").mockResolvedValue({ ...ELEMENT, name: "Edge gateway", version: 4 } as never);
    return () => { get.mockRestore(); put.mockRestore(); };
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: /Edit/ }));
    const dialog = within(within(document.body).getByRole("dialog"));
    const name = dialog.getByLabelText("Name");
    await userEvent.clear(name);
    await userEvent.type(name, "Edge gateway");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/architecture/elements/el-1`, { version: 3, name: "Edge gateway" },
    ));
  },
};

export const MissingElementShowsNotFound: Story = {
  parameters: { elementId: "missing" },
  beforeEach: () => {
    const get = spyOn(api, "get").mockRejectedValue(new Error("Element not found."));
    return () => get.mockRestore();
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText(/Element not found|could not be found/)).toBeInTheDocument();
  },
};
