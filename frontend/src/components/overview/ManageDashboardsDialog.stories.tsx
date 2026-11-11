import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { OrgDashboard } from "../../api/types";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { ManageDashboardsDialog } from "./ManageDashboardsDialog";

const ORG_ID = "org-1";

function page(overrides: Partial<OrgDashboard> = {}): OrgDashboard {
  return { id: "overview", name: "Overview", is_default: true, restricted: false, viewers: [], can_manage: true, ...overrides };
}

const PAGES: OrgDashboard[] = [
  page(),
  page({ id: "p1", name: "Risk board", is_default: false }),
  page({
    id: "p2", name: "Leadership", is_default: false, restricted: true,
    viewers: [{ type: "org_group", id: "g1", label: "Executives", member_count: 4, exists: true }],
  }),
];

/** The administrator's list of dashboard pages: add, rename, limit, order and delete. */
const meta: Meta<typeof ManageDashboardsDialog> = {
  title: "Components/Overview/ManageDashboardsDialog",
  component: ManageDashboardsDialog,
  decorators: [withRouter("/"), withToast()],
  args: { organizationId: ORG_ID, pages: PAGES, onClose: fn(), onChanged: fn() },
};
export default meta;

type Story = StoryObj<typeof ManageDashboardsDialog>;

/** Every page is listed with who may see it; the built-in page has no move or delete. */
export const ListsPagesAndWhoMaySeeThem: Story = {
  play: async () => {
    const dialog = await screen.findByRole("dialog", { name: "Dashboards" });
    await expect(within(dialog).getByText("Built in")).toBeInTheDocument();
    await expect(within(dialog).getByText("Executives")).toBeInTheDocument();
    await expect(within(dialog).getAllByText("Every member").length).toBeGreaterThan(0);
    await expect(within(dialog).queryByRole("button", { name: "Delete Overview" })).not.toBeInTheDocument();
    await expect(within(dialog).queryByRole("button", { name: "Move Overview up" })).not.toBeInTheDocument();
  },
};

/** Moving a page sends the order of every page after the built-in one. */
export const MovingAPageSendsTheNewOrder: Story = {
  play: async ({ args }) => {
    const put = spyOn(api, "put").mockResolvedValue(undefined);
    const dialog = await screen.findByRole("dialog", { name: "Dashboards" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Move Leadership up" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/dashboards/order`, { ids: ["p2", "p1"] }));
    await expect(args.onChanged).toHaveBeenCalled();
  },
};

/** A new page is created from its name alone; who may see it is set once it exists. */
export const CreatingAPageNeedsOnlyAName: Story = {
  play: async ({ args }) => {
    const post = spyOn(api, "post").mockResolvedValue(undefined);
    const dialog = await screen.findByRole("dialog", { name: "Dashboards" });
    await userEvent.click(within(dialog).getByRole("button", { name: "New dashboard" }));
    const form = await screen.findByRole("dialog", { name: "New dashboard" });
    await userEvent.type(within(form).getByLabelText(/Name/), "Delivery");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/dashboards`, { name: "Delivery" }));
    await expect(args.onChanged).toHaveBeenCalled();
  },
};

/** Deleting asks first, because the layout cannot be recovered. */
export const DeletingAsksFirst: Story = {
  play: async ({ args }) => {
    const remove = spyOn(api, "delete").mockResolvedValue(undefined);
    const dialog = await screen.findByRole("dialog", { name: "Dashboards" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete Risk board" }));
    await expect(remove).not.toHaveBeenCalled();
    const confirm = await screen.findByRole("dialog", { name: "Delete Risk board?" });
    await userEvent.click(within(confirm).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/dashboards/p1`));
    await expect(args.onChanged).toHaveBeenCalled();
  },
};

/** The built-in page cannot be renamed: its name field is unavailable. */
export const BuiltInPageCannotBeRenamed: Story = {
  play: async () => {
    const dialog = await screen.findByRole("dialog", { name: "Dashboards" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Edit Overview" }));
    const form = await screen.findByRole("dialog", { name: "Edit Overview" });
    await expect(within(form).getByLabelText(/Name/)).toBeDisabled();
  },
};

/** Copying a page asks the server for a copy (its layout and viewers), which the list then shows. */
export const CopyingAPageAsksForACopy: Story = {
  play: async ({ args }) => {
    const post = spyOn(api, "post").mockResolvedValue(undefined);
    const dialog = await screen.findByRole("dialog", { name: "Dashboards" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Copy Leadership" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/dashboards/p2/copy`, {}));
    await expect(args.onChanged).toHaveBeenCalled();
  },
};
