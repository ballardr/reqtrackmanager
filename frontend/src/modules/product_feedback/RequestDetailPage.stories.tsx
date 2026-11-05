import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import {
  buildDemand, buildExternalRef, buildLoop, buildRequest, buildRequestScheme, CHANNEL_CHOICES, ORG_ID, ORG_USERS, PROJECT_ID,
  REQUEST_ID, SYSTEM_CHOICES,
} from "./requestFixtures";
import { RequestDetailPage } from "./RequestDetailPage";
import type { CloseTheLoop, EnhancementRequest, FeedbackAccess } from "./types";

interface Mock {
  request?: EnhancementRequest;
  access?: FeedbackAccess;
  loop?: CloseTheLoop;
}

const TRIAGER: FeedbackAccess = { can_submit: true, can_triage: true };

function mockApis({ request = buildRequest(), access = TRIAGER, loop = buildLoop() }: Mock = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    const route = path.split("?")[0];
    if (route.endsWith("/product_feedback/access")) return access;
    if (route.endsWith("/external-systems")) return SYSTEM_CHOICES.map((c, i) => ({ id: c.value, name: c.label, display_order: i, is_enabled: true, source: "org" }));
    if (route.endsWith("/request-channels")) return CHANNEL_CHOICES.map((c, i) => ({ id: c.value, name: c.label, display_order: i, is_enabled: true, source: "org" }));
    if (route.includes("/scoring-schemes/enhancement_request")) return buildRequestScheme();
    if (route.endsWith("/demand")) return buildDemand();
    if (route.endsWith("/close-the-loop")) return loop;
    if (route.endsWith("/versions") || route.endsWith("/merges") || route.endsWith("/comments") || route.endsWith("/files")) return [];
    if (route.endsWith(`/requests/${REQUEST_ID}`)) return request;
    if (route.includes("/users")) return ORG_USERS;
    if (route.endsWith("/groups")) return [];
    if (route.endsWith(`/projects/${PROJECT_ID}`)) return { id: PROJECT_ID, organization_id: ORG_ID };
    if (route.includes("/link-graph") || route.includes("/links")) return { nodes: [], edges: [], hidden_count: 0, can_link: true, can_propose: false };
    if (route.includes("/activity")) return [];
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof RequestDetailPage> = {
  title: "Modules/ProductFeedback/RequestDetailPage",
  component: RequestDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    withRouter(`/projects/${PROJECT_ID}/modules/product_feedback/requests/${REQUEST_ID}`, "/projects/:projectId/modules/product_feedback/requests/:requestId"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof RequestDetailPage>;

/** A solution with no Pain Point is flagged in the header; nothing blocks it. */
export const AWarningFlagsARequestWithNoPainPoint: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { name: /Export the list to Excel/ })).toBeInTheDocument();
    await expect(canvas.getByText("No Pain Point linked")).toHaveClass("badge--warning");
  },
};

/** The lifecycle buttons are the server's allowed moves, named for where they go. */
export const LifecycleButtonsFollowTheAllowedMoves: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: /Export the list to Excel/ });
    await expect(canvas.getByRole("button", { name: "Start review" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Decline" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Mark delivered" })).not.toBeInTheDocument();
  },
};

/** Declining needs a reason: the confirm button stays disabled until one is typed, and the reason is sent. */
export const DecliningNeedsAReason: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "post").mockResolvedValue(buildRequest({ status: "declined", decline_reason: "Out of scope" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Decline" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await expect(dialog.getByRole("button", { name: "Decline" })).toBeDisabled();
    await userEvent.type(dialog.getByLabelText(/Decline reason/), "Out of scope");
    await userEvent.click(dialog.getByRole("button", { name: "Decline" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      expect.stringContaining(`/requests/${REQUEST_ID}/transition`), { status: "declined", comment: "Out of scope" },
    ));
  },
};

/** Someone who may not triage sees the request but none of the controls the server would refuse. */
export const ANonTriagerSeesNoEditOrTransitionControls: Story = {
  beforeEach: () => mockApis({ access: { can_submit: true, can_triage: false } }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: /Export the list to Excel/ });
    await waitFor(() => expect(canvas.queryByRole("button", { name: "Start review" })).not.toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: /^Edit/ })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Decline" })).not.toBeInTheDocument();
  },
};

/** When every Requirement realising an accepted request is complete, the page prompts but does not move it. */
export const ReadyToDeliverPromptsWithoutMovingTheStatus: Story = {
  beforeEach: () => {
    mockApis({
      request: buildRequest({ status: "accepted", allowed_next_statuses: ["under_review", "delivered", "declined"], pain_point_count: 1 }),
      loop: buildLoop({ status: "accepted", can_record: false, suggest_delivered: true, all_requirements_complete: true }),
    });
    spyOn(api, "post");
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Ready to deliver?")).toBeInTheDocument();
    await expect(api.post).not.toHaveBeenCalled();
    await expect(canvas.queryByText("No Pain Point linked")).not.toBeInTheDocument();
  },
};

/** A delivered request shows the closing-the-loop panel; an accepted one does not. */
export const DeliveredShowsTheClosingTheLoopPanel: Story = {
  beforeEach: () => mockApis({
    request: buildRequest({ status: "delivered", allowed_next_statuses: ["accepted"], pain_point_count: 1, loop_open_count: 1 }),
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("region", { name: "Closing the loop" })).toBeInTheDocument();
    await expect(canvas.getByText("1 of 2 still to be told.")).toBeInTheDocument();
  },
};

/** A duplicate names the request it was merged into and offers Undo merge in place of lifecycle moves. */
export const ADuplicateOffersUndoMerge: Story = {
  beforeEach: () => mockApis({
    request: buildRequest({
      status: "duplicate", allowed_next_statuses: [], pain_point_count: 1,
      merged_into: { id: "request-7", unique_code: "ENH-007", title: "Canonical" },
    }),
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("button", { name: "Undo merge" })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "ENH-007 Canonical" })).toHaveAttribute(
      "href", `/projects/${PROJECT_ID}/modules/product_feedback/requests/request-7`,
    );
    await expect(canvas.queryByRole("button", { name: "Start review" })).not.toBeInTheDocument();
  },
};

/** The references card lists the request's outside tickets, and a triager can add one without making a new version. */
export const ReferencesAreListedAndAddedFromTheRequestPage: Story = {
  beforeEach: () => {
    mockApis({ request: buildRequest({ external_refs: [buildExternalRef()] }) });
    spyOn(api, "post").mockResolvedValue(buildExternalRef({ id: "ref-9", key: "INC1", system_id: "system-servicenow", system_name: "ServiceNow", url: null }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("link", { name: "PROJ-123" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Add reference" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.selectOptions(dialog.getByLabelText("Reference system"), "system-servicenow");
    await userEvent.type(dialog.getByLabelText("Reference key"), "INC1");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      expect.stringContaining(`/requests/${REQUEST_ID}/references`), { system_id: "system-servicenow", key: "INC1", url: null, role: "delivery" },
    ));
  },
};

/** Removing a reference asks first, then deletes only that reference. */
export const RemovingAReferenceAsksFirst: Story = {
  beforeEach: () => {
    mockApis({ request: buildRequest({ external_refs: [buildExternalRef()] }) });
    spyOn(api, "delete").mockResolvedValue(undefined as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Remove reference PROJ-123" }));
    await expect(api.delete).not.toHaveBeenCalled();
    await userEvent.click(within(within(document.body).getByRole("dialog")).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(expect.stringContaining(`/requests/${REQUEST_ID}/references/ref-1`)));
  },
};

/** Someone who may not triage reads the references but cannot add, change or remove them. */
export const ANonTriagerCannotChangeReferences: Story = {
  beforeEach: () => mockApis({ request: buildRequest({ external_refs: [buildExternalRef()] }), access: { can_submit: true, can_triage: false } }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("link", { name: "PROJ-123" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add reference" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Remove reference/ })).not.toBeInTheDocument();
  },
};
