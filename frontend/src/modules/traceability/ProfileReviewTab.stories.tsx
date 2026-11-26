import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { expectStressStable, STRESS_TEXT } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import {
  buildProfileReview, DANA, mockGets, ORG_ID, ORG_USERS, ORG_USERS_URL, PROFILE_ID, profileReviewUrl,
} from "./policyFixtures";
import { ProfileReviewTab } from "./ProfileReviewTab";
import type { ProfileReview } from "./types";

const meta: Meta<typeof ProfileReviewTab> = {
  title: "Modules/Governance/ProfileReviewTab",
  component: ProfileReviewTab,
  args: { orgId: ORG_ID, profileId: PROFILE_ID },
  decorators: [withRouter("/"), withToast()],
  beforeEach: () => mockGets({ [profileReviewUrl]: buildProfileReview(), [ORG_USERS_URL]: ORG_USERS }),
};
export default meta;

type Story = StoryObj<typeof ProfileReviewTab>;

export const ShowsEachRecordTypesSettings: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const row = (await canvas.findByRole("cell", { name: "Requirement" })).closest("tr")!;
    await expect(within(row).getByText("90")).toBeInTheDocument();
    await expect(within(row).getByText("14")).toBeInTheDocument();
    await expect(within(row).getByText("Dana Whitfield")).toBeInTheDocument();
    const risk = canvas.getByRole("cell", { name: "Risk" }).closest("tr")!;
    await expect(within(risk).getAllByText("Not set")).toHaveLength(3);
  },
};

export const EditingSavesThroughTheProfileEndpoint: Story = {
  play: async ({ canvasElement }) => {
    const next: ProfileReview = buildProfileReview();
    next.types[0].settings = { interval_days: 45, lead_days: 14, default_owner: DANA };
    spyOn(api, "put").mockResolvedValue(next);
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Actions for Requirement" }));
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Edit review settings" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Edit review settings: Requirement" }));
    const interval = dialog.getByLabelText("Review interval (days)");
    await userEvent.clear(interval);
    await userEvent.type(interval, "45");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `${profileReviewUrl}/requirement`, { interval_days: 45, lead_days: 14, default_owner: { type: "user", id: "user-1" } },
    ));
    await expect(await within(document.body).findByText("Review settings for Requirement saved.")).toBeInTheDocument();
    await expect(await canvas.findByText("45")).toBeInTheDocument();
  },
};

export const NoRecordTypeHasASchedule: Story = {
  beforeEach: () => mockGets({ [profileReviewUrl]: { types: [] }, [ORG_USERS_URL]: ORG_USERS }),
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No record type has a review schedule.")).toBeInTheDocument();
  },
};

export const ALoadFailureCanBeRetried: Story = {
  beforeEach: () => { spyOn(api, "get").mockRejectedValue(new Error("Server error.")); },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("Server error.")).toBeInTheDocument();
  },
};

export const LongText: Story = {
  beforeEach: () => {
    const long = (isLong: boolean): ProfileReview => ({
      types: [
        {
          artefact_type: "requirement", label: isLong ? STRESS_TEXT.name : "Requirement", module_key: "",
          settings: { interval_days: 90, lead_days: 14, default_owner: { ...DANA, label: isLong ? STRESS_TEXT.word : DANA.label } },
        },
        { artefact_type: "risk", label: isLong ? STRESS_TEXT.word : "Risk", module_key: "", settings: { interval_days: null, lead_days: null, default_owner: null } },
      ],
    });
    let calls = 0;
    mockGets({ [profileReviewUrl]: () => long(calls++ % 2 === 1), [ORG_USERS_URL]: ORG_USERS });
  },
  render: (args) => <TextStress render={() => <ProfileReviewTab {...args} />} />,
  play: async ({ canvasElement }) => {
    await within(canvasElement).findAllByText("Requirement");
    await expectStressStable(canvasElement);
  },
};

export const DarkTheme: Story = { ...ShowsEachRecordTypesSettings, globals: { theme: "dark" } };
