import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api, ApiError } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { DEFAULT_PROFILE, ENFORCED_PROFILE, ORG_ID, profileScreenResponse, SUB_COMPONENTS } from "./profileFixtures";
import { ProfilePage } from "./ProfilePage";

const meta: Meta<typeof ProfilePage> = {
  title: "Modules/Governance/ProfilePage",
  component: ProfilePage,
  args: { orgId: ORG_ID, profileId: ENFORCED_PROFILE.id, onBack: fn() },
  decorators: [withToast(), withRouter("/")],
};
export default meta;

type Story = StoryObj<typeof ProfilePage>;

/** Reads the profile and the sub-components; every policy part is on so every tab is offered. */
function mockProfile(subComponents = SUB_COMPONENTS) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/modules/traceability/subcomponents")) return subComponents;
    if (path.endsWith("/approval")) return { types: [], role_options: [] };
    const found = profileScreenResponse(path, ENFORCED_PROFILE);
    if (found !== undefined) return found;
    return {};
  });
}

/** The header names the profile and its mode; Overview is open; Profiles returns to the list. */
export const ShowsTheOverview: Story = {
  beforeEach: () => mockProfile(),
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { name: "Safety critical" })).toBeInTheDocument();
    await expect(canvas.getByRole("tab", { name: "Overview", selected: true })).toBeInTheDocument();
    for (const name of ["Lifecycle", "Approval", "Review", "Baseline"]) {
      await expect(canvas.getByRole("tab", { name })).toBeInTheDocument();
    }
    await userEvent.click(canvas.getByRole("button", { name: /Profiles/ }));
    await expect(args.onBack).toHaveBeenCalled();
  },
};

/** A part that is switched off for the organisation has no tab. */
export const LeavesOutTabsOfPartsThatAreOff: Story = {
  beforeEach: () => mockProfile(SUB_COMPONENTS.map((s) => ({ ...s, enabled: s.subcomponent_key === "approval_policies" }))),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("tab", { name: "Approval" });
    await expect(canvas.queryByRole("tab", { name: "Lifecycle" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("tab", { name: "Review" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("tab", { name: "Baseline" })).not.toBeInTheDocument();
  },
};

/** Choosing a tab shows its panel. */
export const SwitchesTab: Story = {
  beforeEach: () => mockProfile(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("tab", { name: "Approval" }));
    await waitFor(() => expect(canvas.getByRole("tab", { name: "Approval", selected: true })).toBeInTheDocument());
    await expect(canvas.getByRole("tabpanel")).toBeInTheDocument();
  },
};

/** A profile that does not exist shows a message and the way back, never a spinner. */
export const NotFound: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(404, "Profile not found."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("This profile does not exist or has been deleted.")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: /Profiles/ })).toBeInTheDocument();
  },
};

/** A failed load offers Retry. */
export const LoadFailure: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(500, "Server error."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("button", { name: "Retry" })).toBeInTheDocument();
  },
};

/** A Default profile opens the same way, with no exemptions section. */
export const DefaultProfile: Story = {
  args: { profileId: DEFAULT_PROFILE.id },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => profileScreenResponse(path, DEFAULT_PROFILE) ?? SUB_COMPONENTS);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: "Standard review" });
    await expect(canvas.queryByRole("heading", { name: "Exemptions" })).not.toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...ShowsTheOverview, globals: { theme: "dark" } };
