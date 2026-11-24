import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgGroup, OrgUser, Principal } from "../api/types";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { DetailLayout } from "./DetailLayout";
import { useWatchingTab } from "../hooks/useWatchingTab";

const RECORD = "/api/v1/projects/project-1/requirements/req-1";

const PLATFORM: Principal = { type: "org_group", id: "group-1", label: "Platform Team", member_count: 4, exists: true };
const ALEX: Principal = { type: "user", id: "user-2", label: "Alex Morgan", member_count: null, exists: true };
const SAM: OrgUser = {
  user_id: "user-3", email: "sam@example.com", display_name: "Sam Rivera", is_active: true, is_archived: false, roles: ["member"],
  display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
};
const ORG_GROUPS: OrgGroup[] = [
  { id: "group-1", name: "Platform Team", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
  { id: "group-2", name: "Safety Board", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];

function mockApis(watching: Principal[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `${RECORD}/watchers`) return watching as never;
    if (path.endsWith("/orgs/org-1/groups")) return ORG_GROUPS as never;
    if (path.endsWith("/projects/project-1/groups")) return [] as never;
    if (path.includes("/users/search")) return { members: [SAM], external: null } as never;
    return { members: [], external: null } as never;
  });
}

/** The tab exactly as a record page mounts it: in the aside card of `DetailLayout`, beside Links. */
function Harness({ canManage }: { canManage: boolean }) {
  const tab = useWatchingTab({ recordPath: RECORD, organizationId: "org-1", projectId: "project-1", canManage });
  return (
    <DetailLayout contained={false} aside={<div>Links content</div>} extraTabs={tab ? [tab] : []}>
      <h1 style={{ margin: 0 }}>Record</h1>
    </DetailLayout>
  );
}

const meta: Meta<typeof Harness> = {
  title: "Components/WatchingPanel",
  component: Harness,
  args: { canManage: true },
  decorators: [withStatefulAuth(buildUser()), withToast(), withRouter("/")],
};
export default meta;

type Story = StoryObj<typeof Harness>;

/** The tab label carries the count, so who is watching is visible before the tab is opened. */
export const TabLabelShowsTheCount: Story = {
  beforeEach: () => mockApis([PLATFORM, ALEX]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("tab", { name: "Watching (2)" }));
    await expect(canvas.getByText("Platform Team")).toBeVisible();
    await expect(canvas.getByText("Alex Morgan")).toBeVisible();
    await expect(canvas.getByText("Organisation group, 4 members")).toBeVisible();
    await expect(canvas.getByRole("button", { name: "Stop watching: Alex Morgan" })).toBeInTheDocument();
  },
};

/** A manager of an unwatched record sees a plain "Watching" tab with only the (+) button to add. */
export const ManagerSeesAnEmptyTabWithAddButton: Story = {
  beforeEach: () => mockApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("tab", { name: "Watching" }));
    await expect(canvas.getByText("No one is watching.")).toBeVisible();
    await expect(canvas.getByRole("button", { name: "Add watching user or group" })).toBeVisible();
    await expect(canvas.queryByRole("combobox")).not.toBeInTheDocument();
  },
};

/** The (+) opens the picker in a popover; picking a group posts it as a typed principal and lists it. */
export const ManagerAddsAGroup: Story = {
  beforeEach: () => {
    mockApis([]);
    spyOn(api, "post").mockResolvedValue([{ ...PLATFORM, id: "group-2", label: "Safety Board" }] as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("tab", { name: "Watching" }));
    await userEvent.click(canvas.getByRole("button", { name: "Add watching user or group" }));
    const body = within(canvasElement.ownerDocument.body);
    await userEvent.type(await body.findByRole("combobox", { name: "Add watching user or group" }), "safety");
    await userEvent.click(await body.findByText("Safety Board"));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${RECORD}/watchers`, { principal: { type: "org_group", id: "group-2" } }));
    await waitFor(() => expect(canvas.getByRole("tab", { name: "Watching (1)" })).toBeInTheDocument());
  },
};

/** A user can be picked as well as a group (users and groups on parity). */
export const ManagerAddsAUser: Story = {
  beforeEach: () => {
    mockApis([]);
    spyOn(api, "post").mockResolvedValue([{ ...ALEX, id: "user-3", label: "Sam Rivera" }] as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("tab", { name: "Watching" }));
    await userEvent.click(canvas.getByRole("button", { name: "Add watching user or group" }));
    const body = within(canvasElement.ownerDocument.body);
    await userEvent.type(await body.findByRole("combobox", { name: "Add watching user or group" }), "sam");
    await userEvent.click(await body.findByText("Sam Rivera"));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${RECORD}/watchers`, { principal: { type: "user", id: "user-3" } }));
  },
};

/** Removing a watcher calls the DELETE endpoint for that principal and shows the remaining list. */
export const ManagerRemovesAWatcher: Story = {
  beforeEach: () => {
    mockApis([ALEX]);
    spyOn(api, "delete").mockResolvedValue([] as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("tab", { name: "Watching (1)" }));
    await userEvent.click(canvas.getByRole("button", { name: "Stop watching: Alex Morgan" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${RECORD}/watchers/user/user-2`));
    await waitFor(() => expect(canvas.getByText("No one is watching.")).toBeInTheDocument());
  },
};

/** A reader sees who is watching but can neither add nor remove. */
export const ReaderSeesButCannotChange: Story = {
  args: { canManage: false },
  beforeEach: () => mockApis([PLATFORM]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("tab", { name: "Watching (1)" }));
    await expect(canvas.getByText("Platform Team")).toBeVisible();
    await expect(canvas.queryByRole("button", { name: /Stop watching/ })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add watching user or group" })).not.toBeInTheDocument();
  },
};

/** With no one watching, a reader gets no Watching tab at all (Links alone, as before the tab existed). */
export const ReaderSeesNoTabWhenNoOneWatches: Story = {
  args: { canManage: false },
  beforeEach: () => mockApis([]),
  play: async ({ canvasElement }) => {
    await new Promise((resolve) => setTimeout(resolve, 100));
    await expect(within(canvasElement).queryByRole("tab", { name: /Watching/ })).not.toBeInTheDocument();
    await expect(within(canvasElement).getByText("Links content")).toBeVisible();
  },
};
