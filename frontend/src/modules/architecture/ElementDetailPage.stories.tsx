import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildComment, buildPin } from "../../testing/recordCommentsFake";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildConnection, buildElement, buildRecordDiagram, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { ElementDetailPage } from "./ElementDetailPage";

const PARENT = buildElement({ id: "el-0", unique_code: "ELM-000", name: "Platform", ports: [] });
const ELEMENT = buildElement({ parent_id: "el-0", version: 3, display_note: "Public entry point." });
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
    const connections = within(canvas.getByRole("list", { name: "Connections of this element" }));
    await expect(connections.getByRole("link", { name: "CON-001" })).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/architecture/connections/con-1`);
    await expect(connections.getByText("Client traffic")).toBeInTheDocument();
    await expect(await canvas.findByText("Shared infrastructure · 1 grant")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Change status" })).toBeInTheDocument();
    // The display note (drawn in the box) is shown apart from the description.
    await expect(canvas.getByText("Public entry point.")).toBeInTheDocument();
    await expect(canvas.getByText("Terminates client traffic.")).toBeInTheDocument();
  },
};

/** An element another owner shares is read-only: no Edit, no status menu, no port controls, no Add child. */
/** The Diagrams card is the second card, directly under the details, so another view of the element is the first thing to reach. */
export const DiagramsCardFollowsTheDetailsCard: Story = {
  beforeEach: () => {
    const get = mockArchitectureReads({ elements: [PARENT, ELEMENT, CHILD], element: ELEMENT, recordDiagrams: [buildRecordDiagram()] });
    return () => get.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: /DGM-001 Main system/ });
    const cards = Array.from(canvasElement.querySelectorAll("section.card")).map((c) => c.getAttribute("aria-label"));
    await expect(cards.slice(0, 3)).toEqual(["Details", "Diagrams", "Ports"]);
    await expect(canvas.getByRole("button", { name: "New state machine diagram" })).toBeInTheDocument();
  },
};

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
    await expect(canvas.queryByRole("button", { name: "Change status" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add child" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add port" })).not.toBeInTheDocument();
    await expect(canvas.getByText(/only its owner changes it/)).toBeInTheDocument();
  },
};

/** The menu offers the moves the server returned for the record's status, named from the current status. */
export const ChangeStateOffersTheServersMoves: Story = {
  beforeEach: () => {
    const draft = buildElement({ status: "draft", version: 3 });
    const get = mockArchitectureReads({ elements: [PARENT, draft], element: draft, connections: [] });
    return () => get.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Change status" }));
    const menu = within(document.body).getByRole("menu", { name: "Change status" });
    await expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent?.trim())).toEqual([
      "Move from Draft to Proposed", "Move from Draft to Active", "Move from Draft to Rejected",
    ]);
  },
};

/** The menu button's own tooltip describes every status, not only the current one. */
export const ChangeStateHelpDescribesEveryState: Story = {
  beforeEach: () => {
    const get = mockArchitectureReads({ elements: [PARENT, ELEMENT], element: ELEMENT, connections: [] });
    return () => get.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.hover(await canvas.findByRole("button", { name: "Change status" }));
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
    await userEvent.click(await canvas.findByRole("button", { name: "Change status" }));
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


/** The element's own comments are listed, and the threads pinned to it on diagrams link to those diagrams with the thread open. */
export const ShowsItsCommentsAndTheThreadsPinnedToItOnDiagrams: Story = {
  beforeEach: () => {
    const get = mockArchitectureReads({
      elements: [PARENT, ELEMENT, CHILD], element: ELEMENT, connections: [],
      comments: { comments: [buildComment({ id: "c-1", body: "Check the TLS settings." })] },
      anchoredComments: [{
        record_type: "architecture_diagram", record_id: "dgm-1", record_label: "DGM-001 Platform overview",
        pin: buildPin({ id: "p-9", anchor_kind: "node", anchor_key: "el-1", comment_count: 1, resolved: true }),
        comments: [buildComment({ id: "c-9", pin_id: "p-9", body: "Move this behind the proxy." })],
      }],
    });
    return () => get.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Check the TLS settings.")).toBeInTheDocument();
    const link = await canvas.findByRole("link", { name: "Open DGM-001 Platform overview" });
    await expect(link).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/architecture/diagrams/dgm-1?pin=p-9`);
    await expect(canvas.getByText("Move this behind the proxy.")).toBeInTheDocument();
    await expect(canvas.getByText("Resolved")).toBeInTheDocument();
  },
};

/** An element's description is Markdown, while its display note (text drawn in the box) stays plain. */
export const DescriptionIsFormattedAndTheDisplayNoteIsPlain: Story = {
  beforeEach: () => {
    const marked = buildElement({
      parent_id: "el-0", version: 3, description: "Handles **all** inbound traffic:\n\n- auth\n- routing", display_note: "Use **as is**",
    });
    const get = mockArchitectureReads({ elements: [PARENT, marked], element: marked, connections: [] });
    return () => get.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { name: /Gateway/ })).toBeInTheDocument();
    await expect(canvasElement.querySelector(".markdown-view strong")).toHaveTextContent("all");
    await expect(canvasElement.querySelectorAll(".markdown-view li")).toHaveLength(2);
    await expect(canvas.getByText("Use **as is**")).toBeInTheDocument();
  },
};
