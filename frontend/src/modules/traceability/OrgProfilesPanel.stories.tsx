import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { expectHeaderOrdersText } from "../../testing/sortHelpers";
import { expectStressStable, stressText } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { DEFAULT_PROFILE, ENFORCED_PROFILE, ORG_ID, ORG_PROJECTS, OPT_IN_PROFILE, profileScreenResponse } from "./profileFixtures";
import { OrgProfilesPanel } from "./OrgProfilesPanel";

const BASE = `/api/v1/orgs/${ORG_ID}/modules/traceability/profiles`;
const PROFILES = [ENFORCED_PROFILE, DEFAULT_PROFILE, OPT_IN_PROFILE];

const meta: Meta<typeof OrgProfilesPanel> = {
  title: "Modules/Governance/OrgProfilesPanel",
  component: OrgProfilesPanel,
  args: { orgId: ORG_ID },
  decorators: [withToast(), withStatefulAuth(buildUser({ ui_preferences: {} })), withRouter("/")],
};
export default meta;

type Story = StoryObj<typeof OrgProfilesPanel>;

/** Serves the list and the other reads the panel and a profile page make. */
function mockReads(profiles = PROFILES) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === BASE) return profiles;
    const opened = profiles.find((p) => path.endsWith(`/profiles/${p.id}`));
    const found = profileScreenResponse(path, opened ?? ENFORCED_PROFILE);
    if (found !== undefined) return found;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

/** Each profile shows its mode, reach, exemptions and the policy it holds; the columns order the rows. */
export const ListsProfiles: Story = {
  beforeEach: () => mockReads(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Governance profiles" });
    await expect(within(table).getByText("Enforced")).toBeInTheDocument();
    await expect(within(table).getByText("2 projects")).toBeInTheDocument();
    await expect(within(table).getByText("Approval policy 2, Review policy 1")).toBeInTheDocument();
    await expectHeaderOrdersText(table, "Name");
  },
};

/** With no profile the empty state says what a profile is; New profile is the one call to action. */
export const Empty: Story = {
  beforeEach: () => mockReads([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(/No governance profiles yet/)).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "New profile" })).toBeInTheDocument();
  },
};

/** Opening a profile replaces the list with the profile's page; Profiles returns to the list. */
export const OpensAProfile: Story = {
  beforeEach: () => mockReads(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Safety critical" }));
    await expect(await canvas.findByRole("heading", { name: "Safety critical" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: /Profiles/ }));
    await expect(await canvas.findByRole("table", { name: "Governance profiles" })).toBeInTheDocument();
  },
};

/** Delete asks first, naming what is removed, then calls the endpoint and reloads the list. */
export const DeletesAfterConfirming: Story = {
  beforeEach: () => {
    mockReads();
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Actions for Standard review" }));
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Delete profile" }));
    const confirm = within(await within(document.body).findByRole("dialog", { name: "Delete profile" }));
    await expect(confirm.getByText(/policy rows are removed/)).toBeInTheDocument();
    await userEvent.click(confirm.getByRole("button", { name: "Delete profile" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${BASE}/prof-2`));
    await expect(await within(document.body).findByText("Profile deleted.")).toBeInTheDocument();
  },
};

/** New profile opens the dialog; creating a profile opens it. */
export const CreatesAndOpensTheProfile: Story = {
  beforeEach: () => {
    mockReads();
    spyOn(api, "post").mockResolvedValue(DEFAULT_PROFILE);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "New profile" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "New profile" }));
    await waitFor(() => expect(ORG_PROJECTS.length).toBeGreaterThan(0));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Standard review");
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    await expect(await canvas.findByRole("tab", { name: "Overview" })).toBeInTheDocument();
  },
};

/** A refused load offers Retry. */
export const LoadFailure: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("Server error."));
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("button", { name: "Retry" })).toBeInTheDocument();
  },
};

/** Long profile names keep the columns and the row menus where they are. */
export const LongText: Story = {
  beforeEach: () => {
    const listOf = (long: boolean) => [
      { ...ENFORCED_PROFILE, name: stressText(long, ENFORCED_PROFILE.name) },
      { ...DEFAULT_PROFILE, name: stressText(long, DEFAULT_PROFILE.name, "word") },
    ];
    spyOn(api, "get").mockImplementation(async (path: string) => listOf(path.includes("org-long")));
  },
  render: (args) => (
    <TextStress render={(long) => <OrgProfilesPanel {...args} orgId={long ? "org-long" : "org-short"} />} />
  ),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(canvasElement.querySelectorAll("table").length).toBe(2));
    await expectStressStable(canvasElement);
  },
};

export const DarkTheme: Story = { ...ListsProfiles, globals: { theme: "dark" } };
