import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { AllocationPanel } from "./AllocationPanel";
import { buildAllocationPair, buildAllocationView, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";

const BASE = `/api/v1/projects/${PROJECT_ID}/modules/architecture`;
const REQUIREMENT = { kind: "requirement", requirementId: "req-1" } as const;

const meta: Meta<typeof AllocationPanel> = {
  title: "Modules/Architecture/AllocationPanel",
  component: AllocationPanel,
  args: { projectId: PROJECT_ID, perspective: REQUIREMENT },
  decorators: [withAuth(buildUser({ id: "user-1" })), withRouter(`/projects/${PROJECT_ID}/requirements/req-1`), withToast()],
};
export default meta;

type Story = StoryObj<typeof AllocationPanel>;

/** A requirement's card lists the elements it is allocated to, with their status, as links to the elements. */
export const ListsTheElementsARequirementIsAllocatedTo: Story = {
  beforeEach: () => { mockArchitectureReads({ allocation: buildAllocationView({ allocated: [buildAllocationPair({ link_id: "link-1" })] }) }); },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Architecture" }));
    await expect(card.getByRole("link", { name: /ELM-001 Gateway/ })).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/architecture/elements/el-1`);
    await expect(card.getByText("Active")).toBeInTheDocument();
    await expect(card.queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
  },
};

/** Accept turns the suggestion into a link and the card reads again. */
export const AcceptingASuggestionPostsThePair: Story = {
  beforeEach: () => {
    mockArchitectureReads({ allocation: buildAllocationView({ suggested: [buildAllocationPair()] }) });
    spyOn(api, "post").mockResolvedValue({ accepted: 1, failed: [] } as never);
  },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Architecture" }));
    await userEvent.click(card.getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/allocation/accept`, { pairs: [{ requirement_id: "req-REQ-001", element_id: "el-1" }] }));
    await expect(await within(document.body).findByText("Allocation added.")).toBeInTheDocument();
  },
};

/** Accept all sends every suggested pair in one request. */
export const AcceptAllSendsEverySuggestion: Story = {
  beforeEach: () => {
    mockArchitectureReads({ allocation: buildAllocationView({ suggested: [buildAllocationPair(), buildAllocationPair({ code: "REQ-002", name: "Audit log" })] }) });
    spyOn(api, "post").mockResolvedValue({ accepted: 2, failed: [] } as never);
  },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Architecture" }));
    await userEvent.click(card.getByRole("button", { name: "Accept all" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/allocation/accept`, expect.objectContaining({ pairs: expect.arrayContaining([expect.objectContaining({ requirement_id: "req-REQ-002" })]) })));
    await expect(await within(document.body).findByText("2 allocations added.")).toBeInTheDocument();
  },
};

/** A pair the server refuses (an approved requirement that needs a change request) is reported with its reason. */
export const ARefusedPairIsReportedWithItsReason: Story = {
  beforeEach: () => {
    mockArchitectureReads({ allocation: buildAllocationView({ suggested: [buildAllocationPair()] }) });
    spyOn(api, "post").mockResolvedValue({ accepted: 0, failed: [{ requirement_id: "req-REQ-001", element_id: "el-1", reason: "A change request is required." }] } as never);
  },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Architecture" }));
    await userEvent.click(card.getByRole("button", { name: "Accept" }));
    await expect(await within(document.body).findByText(/A change request is required\./)).toBeInTheDocument();
  },
};

/** Dismiss hides a suggestion; a dismissed one offers Restore. */
export const DismissAndRestorePostTheirPair: Story = {
  beforeEach: () => {
    mockArchitectureReads({ allocation: buildAllocationView({ suggested: [buildAllocationPair()], dismissed: [buildAllocationPair({ code: "REQ-003", name: "Old idea" })] }) });
    spyOn(api, "post").mockResolvedValue(undefined as never);
  },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Architecture" }));
    await userEvent.click(card.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/allocation/dismiss`, { requirement_id: "req-REQ-001", element_id: "el-1" }));
    await userEvent.click(card.getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/allocation/restore`, { requirement_id: "req-REQ-003", element_id: "el-1" }));
  },
};

/** A person who cannot change links reads the lists and is offered no button. */
export const ReadOnlyWithoutLinkAuthority: Story = {
  beforeEach: () => { mockArchitectureReads({ allocation: buildAllocationView({ can_manage: false, suggested: [buildAllocationPair()], dismissed: [buildAllocationPair({ code: "REQ-003" })] }) }); },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Architecture" }));
    await expect(card.getAllByRole("link").length).toBe(2);
    await expect(card.queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
    await expect(card.queryByRole("button", { name: "Restore" })).not.toBeInTheDocument();
  },
};

/** An element's card lists the requirements, each a link to the requirement. */
export const AnElementsCardListsRequirements: Story = {
  args: { perspective: { kind: "element", elementId: "el-1" } },
  beforeEach: () => { mockArchitectureReads({ allocation: buildAllocationView({ allocated: [buildAllocationPair({ link_id: "link-1" })], suggested: [buildAllocationPair({ code: "REQ-002", name: "Audit log" })] }) }); },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Requirements" }));
    await expect(card.getByRole("link", { name: /REQ-001 Report latency/ })).toHaveAttribute("href", `/projects/${PROJECT_ID}/requirements/req-REQ-001`);
    await expect(card.getByRole("link", { name: /REQ-002 Audit log/ })).toBeInTheDocument();
  },
};

/** With nothing allocated, suggested or dismissed the card is not drawn. */
export const NothingToShowDrawsNoCard: Story = {
  beforeEach: () => { mockArchitectureReads(); },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("region")).not.toBeInTheDocument();
  },
};
