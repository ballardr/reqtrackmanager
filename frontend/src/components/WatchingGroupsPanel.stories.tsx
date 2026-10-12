import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgGroup, Principal } from "../api/types";
import { withToast } from "../testing/storybook-helpers";
import { WatchingGroupsPanel } from "./WatchingGroupsPanel";

const RECORD = "/api/v1/projects/project-1/requirements/req-1";

const PLATFORM: Principal = { type: "org_group", id: "group-1", label: "Platform Team", member_count: 4, exists: true };
const ORG_GROUPS: OrgGroup[] = [
  { id: "group-1", name: "Platform Team", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
  { id: "group-2", name: "Safety Board", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];

function mockApis(watching: Principal[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `${RECORD}/watchers`) return watching as never;
    if (path.endsWith("/orgs/org-1/groups")) return ORG_GROUPS as never;
    if (path.endsWith("/projects/project-1/groups")) return [] as never;
    return { members: [], external: null } as never;
  });
}

const meta: Meta<typeof WatchingGroupsPanel> = {
  title: "Components/WatchingGroupsPanel",
  component: WatchingGroupsPanel,
  args: { recordPath: RECORD, organizationId: "org-1", projectId: "project-1", canManage: true },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof WatchingGroupsPanel>;

/** A manager sees who is watching, with the kind and size of each group, and a remove action. */
export const ManagerSeesWatchingGroups: Story = {
  beforeEach: () => mockApis([PLATFORM]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Platform Team")).toBeInTheDocument());
    await expect(canvas.getByText("Org group · 4 members")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Stop watching: Platform Team" })).toBeInTheDocument();
  },
};

/** Adding a group posts it as a typed principal and shows the returned list. */
export const ManagerAddsAGroup: Story = {
  beforeEach: () => {
    mockApis([]);
    spyOn(api, "post").mockResolvedValue([{ ...PLATFORM, id: "group-2", label: "Safety Board" }] as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No group is watching.")).toBeInTheDocument());
    await userEvent.type(canvas.getByRole("combobox", { name: "Add watching group" }), "safety");
    await userEvent.click(await canvas.findByText("Safety Board"));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${RECORD}/watchers`, { group: { type: "org_group", id: "group-2" } }));
    await waitFor(() => expect(canvas.getAllByText("Safety Board").length).toBeGreaterThan(0));
  },
};

/** Removing a group calls the DELETE endpoint for that group and shows the remaining list. */
export const ManagerRemovesAGroup: Story = {
  beforeEach: () => {
    mockApis([PLATFORM]);
    spyOn(api, "delete").mockResolvedValue([] as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Stop watching: Platform Team" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${RECORD}/watchers/org_group/group-1`));
    await waitFor(() => expect(canvas.getByText("No group is watching.")).toBeInTheDocument());
  },
};

/** A reader sees the watching groups but can neither add nor remove them. */
export const ReaderSeesButCannotChange: Story = {
  args: { canManage: false },
  beforeEach: () => mockApis([PLATFORM]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Platform Team")).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: /Stop watching/ })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("combobox")).not.toBeInTheDocument();
  },
};

/** With nothing to show a reader, the panel renders nothing at all. */
export const ReaderSeesNothingWhenNoGroupWatches: Story = {
  args: { canManage: false },
  beforeEach: () => mockApis([]),
  play: async ({ canvasElement }) => {
    await new Promise((resolve) => setTimeout(resolve, 100));
    await expect(within(canvasElement).queryByRole("region")).not.toBeInTheDocument();
  },
};
