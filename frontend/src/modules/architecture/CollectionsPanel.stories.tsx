import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { buildElement, mockArchitectureReads, ORG_ID, ORG_USERS, PROJECT_ID } from "./architectureFixtures";
import { CollectionsPanel } from "./CollectionsPanel";

const ELEMENTS = [buildElement(), buildElement({ id: "el-2", unique_code: "ELM-002", name: "Orders", ports: [] })];

const meta: Meta<typeof CollectionsPanel> = {
  title: "Modules/Architecture/CollectionsPanel",
  component: CollectionsPanel,
  args: { scope: { kind: "project", projectId: PROJECT_ID }, elements: ELEMENTS, orgUsers: ORG_USERS, organizationId: ORG_ID },
  decorators: [withToast()],
  beforeEach: () => {
    const get = mockArchitectureReads();
    return () => get.mockRestore();
  },
};
export default meta;

type Story = StoryObj<typeof CollectionsPanel>;

export const ShowsMembersAndWhoItIsSharedWith: Story = {
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Shared infrastructure" }));
    await expect(await card.findByText("ELM-001 Gateway")).toBeInTheDocument();
    await expect(card.getByText("Billing (BILL) and nested projects")).toBeInTheDocument();
  },
};

/** Sharing with a project posts the grant, with the descendants flag only when ticked. */
export const SharingWithAProjectPostsTheGrant: Story = {
  beforeEach: () => {
    const get = mockArchitectureReads();
    get.mockImplementation(async (path: string) => {
      if (path.includes("/api/v1/projects?")) return [{ id: "project-2", name: "Billing", code: "BILL" }] as never;
      if (path.endsWith("/collections")) return [{ ...(await import("./architectureFixtures")).buildCollection({ grants: [], grant_count: 0 }) }] as never;
      if (path.endsWith("/members")) return [] as never;
      throw new Error(`Unmocked GET: ${path}`);
    });
    const post = spyOn(api, "post").mockResolvedValue({} as never);
    return () => { get.mockRestore(); post.mockRestore(); };
  },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Shared infrastructure" }));
    await expect(await card.findByText("Not shared with anyone yet.")).toBeInTheDocument();
    await expect(card.getByRole("button", { name: "Share" })).toBeDisabled();
    await waitFor(() => expect(within(card.getByLabelText("Project")).getByText("Billing (BILL)")).toBeInTheDocument());
    await userEvent.selectOptions(card.getByLabelText("Project"), "project-2");
    await userEvent.click(card.getByRole("checkbox", { name: "Include nested projects" }));
    await userEvent.click(card.getByRole("button", { name: "Share" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/architecture/collections/col-1/grants`,
      { project_id: "project-2", group: null, include_descendants: true },
    ));
  },
};

export const DeletingACollectionAsksFirst: Story = {
  beforeEach: () => {
    const del = spyOn(api, "delete").mockResolvedValue(undefined as never);
    return () => del.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Shared infrastructure" }));
    await userEvent.click(card.getByRole("button", { name: "Delete" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await expect(dialog.getByText(/lose that access/)).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/modules/architecture/collections/col-1`));
  },
};
