import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { expectHeaderOrdersText } from "../../testing/sortHelpers";
import { expectStressStable, stressText } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { DEFAULT_PROFILE, ENFORCED_PROFILE, ORG_ID, ORG_PROJECTS } from "./profileFixtures";
import { ProfileOverviewTab } from "./ProfileOverviewTab";
import type { ProfileDetail } from "./types";

const BASE = `/api/v1/orgs/${ORG_ID}/modules/traceability/profiles/${ENFORCED_PROFILE.id}`;

const meta: Meta<typeof ProfileOverviewTab> = {
  title: "Modules/Governance/ProfileOverviewTab",
  component: ProfileOverviewTab,
  args: { orgId: ORG_ID, profile: ENFORCED_PROFILE, onChange: fn() },
  decorators: [withToast(), withRouter("/")],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(ORG_PROJECTS);
  },
};
export default meta;

type Story = StoryObj<typeof ProfileOverviewTab>;

/** An Enforced profile shows its exemptions and the effect on each project it reaches. */
export const EnforcedProfile: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("table", { name: "Exempt projects" })).toBeInTheDocument();
    const impact = canvas.getByRole("table", { name: "Projects reached by this profile" });
    await expect(within(impact).getByText("Enforced")).toBeInTheDocument();
    await expect(within(impact).getByText("Exempt")).toBeInTheDocument();
    await expectHeaderOrdersText(impact, "Project");
  },
};

/** A Default profile has no exemptions section; its effect table says who opted out. */
export const DefaultProfileHasNoExemptions: Story = {
  args: { profile: DEFAULT_PROFILE },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Add exemption" })).not.toBeInTheDocument();
    await expect(canvas.getAllByText("Opted out").length).toBeGreaterThan(0);
    await expect(canvas.getByText("No choice")).toBeInTheDocument();
  },
};

/** Changing a profile to Enforced asks first because it binds every project it reaches; cancelling sends nothing. */
export const EnforcingAProfileAsksFirst: Story = {
  args: { profile: DEFAULT_PROFILE },
  play: async ({ canvasElement, args }) => {
    const updated: ProfileDetail = { ...DEFAULT_PROFILE, mode: "enforced" };
    const patch = spyOn(api, "patch").mockResolvedValue(updated);
    const canvas = within(canvasElement);
    const details = within(canvas.getByRole("region", { name: "Details" }));
    await userEvent.selectOptions(details.getByRole("combobox", { name: "Mode" }), "Enforced");
    await userEvent.click(details.getByRole("button", { name: "Save" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Enforce profile" }));
    await userEvent.click(dialog.getByRole("button", { name: "Cancel" }));
    await expect(patch).not.toHaveBeenCalled();
    await userEvent.click(details.getByRole("button", { name: "Save" }));
    await userEvent.click(within(await within(document.body).findByRole("dialog", { name: "Enforce profile" })).getByRole("button", { name: "Enforce profile" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/modules/traceability/profiles/${DEFAULT_PROFILE.id}`, expect.objectContaining({ mode: "enforced" })));
    await waitFor(() => expect(args.onChange).toHaveBeenCalledWith(updated));
  },
};

/** Save is unavailable until a detail changes; it sends only the details group and hands the result to the page. */
export const SavesTheDetails: Story = {
  play: async ({ canvasElement, args }) => {
    const updated: ProfileDetail = { ...ENFORCED_PROFILE, name: "Safety critical programme", mode: "default" };
    spyOn(api, "patch").mockResolvedValue(updated);
    const canvas = within(canvasElement);
    const details = within(canvas.getByRole("region", { name: "Details" }));
    await expect(details.getByRole("button", { name: "Save" })).toBeDisabled();
    const name = details.getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Safety critical programme");
    await userEvent.selectOptions(details.getByRole("combobox", { name: "Mode" }), "default");
    await userEvent.click(details.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(BASE, {
      name: "Safety critical programme", description: "Every project that ships to customers.", mode: "default",
    }));
    await waitFor(() => expect(args.onChange).toHaveBeenCalledWith(updated));
    await expect(await within(document.body).findByText("Profile saved.")).toBeInTheDocument();
  },
};

/** Changing the reach saves the target kind and projects through the reach group's own Save. */
export const SavesTheReach: Story = {
  play: async ({ canvasElement, args }) => {
    spyOn(api, "put").mockResolvedValue(DEFAULT_PROFILE);
    const canvas = within(canvasElement);
    const reach = within(canvas.getByRole("region", { name: "Reach" }));
    await userEvent.selectOptions(reach.getByRole("combobox", { name: "Reaches" }), "all_projects");
    await userEvent.click(reach.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${BASE}/targets`, { target_kind: "all_projects", targets: [] }));
    await waitFor(() => expect(args.onChange).toHaveBeenCalledWith(DEFAULT_PROFILE));
  },
};

/** Adding an exemption opens the dialog; removing one asks first and then calls the endpoint. */
export const RemovesAnExemptionAfterConfirming: Story = {
  play: async ({ canvasElement, args }) => {
    const updated = { ...ENFORCED_PROFILE, exemptions: [] };
    spyOn(api, "delete").mockResolvedValue(updated);
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add exemption" }));
    await expect(await within(document.body).findByRole("dialog", { name: "Add exemption" })).toBeInTheDocument();
    await userEvent.click(within(document.body).getByRole("button", { name: "Close" }));
    await userEvent.click(canvas.getByRole("button", { name: "Actions for the exemption of SIG Signalling upgrade" }));
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Remove exemption" }));
    const confirm = within(await within(document.body).findByRole("dialog", { name: "Remove exemption" }));
    await userEvent.click(confirm.getByRole("button", { name: "Remove exemption" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${BASE}/exemptions/proj-2`));
    await waitFor(() => expect(args.onChange).toHaveBeenCalledWith(updated));
  },
};

/** A failed save is drawn beside the Save button and nothing is handed on. */
export const FailedSaveIsShown: Story = {
  play: async ({ canvasElement, args }) => {
    spyOn(api, "patch").mockRejectedValue(new Error("A profile with this name already exists."));
    const canvas = within(canvasElement);
    const details = within(canvas.getByRole("region", { name: "Details" }));
    await userEvent.type(details.getByRole("textbox", { name: "Name" }), " 2");
    await userEvent.click(details.getByRole("button", { name: "Save" }));
    await expect(await details.findByText("A profile with this name already exists.")).toBeInTheDocument();
    await expect(args.onChange).not.toHaveBeenCalled();
  },
};

/** More than ten projects: ten rows show and the rest are behind Show all. */
export const ManyProjectsAreCapped: Story = {
  args: {
    profile: {
      ...DEFAULT_PROFILE,
      projects: Array.from({ length: 14 }, (_, i) => ({
        project_id: `p-${i}`, project_name: `Project ${String(i).padStart(2, "0")}`, outcome: "default" as const, applies: true, choice: null,
      })),
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = canvas.getByRole("table", { name: "Projects reached by this profile" });
    await expect(within(table).getAllByRole("row")).toHaveLength(11);
    await expect(canvas.getByRole("button", { name: "Show all 14 projects" })).toBeInTheDocument();
  },
};

/** Long names and reasons stay in their cells; the tables keep their columns and row menus. */
export const LongText: Story = {
  render: (args) => (
    <TextStress render={(long) => (
      <ProfileOverviewTab
        {...args}
        profile={{
          ...ENFORCED_PROFILE,
          exemptions: [{ ...ENFORCED_PROFILE.exemptions[0], project_name: stressText(long, "SIG Signalling upgrade"), reason: stressText(long, "Superseded.", "summary") }],
          projects: ENFORCED_PROFILE.projects.map((p, i) => (i === 0 ? { ...p, project_name: stressText(long, p.project_name, "word") } : p)),
        }}
      />
    )} />
  ),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(canvasElement.querySelectorAll("table").length).toBeGreaterThanOrEqual(4));
    await expectStressStable(canvasElement);
  },
};

export const DarkTheme: Story = { ...EnforcedProfile, globals: { theme: "dark" } };
