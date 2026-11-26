import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { expectStressStable, stressText } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { ProjectProfilesPanel } from "./ProjectProfilesPanel";
import type { ProjectProfile, ProjectProfiles } from "./types";

const PROJECT_ID = "project-1";
const URL = `/api/v1/projects/${PROJECT_ID}/modules/traceability/profiles`;

const ENFORCED: ProjectProfile = {
  id: "p-1", name: "Safety critical", description: "Every project that ships to customers.", mode: "enforced",
  outcome: "enforced", applies: true, choice: null, can_choose: false,
};
const DEFAULT: ProjectProfile = {
  id: "p-2", name: "Standard review", description: "Quarterly review of every record.", mode: "default",
  outcome: "default", applies: true, choice: null, can_choose: true,
};
const OPT_IN: ProjectProfile = {
  id: "p-3", name: "Audit ready", description: "Adds baseline checks.", mode: "opt_in",
  outcome: "available", applies: false, choice: null, can_choose: true,
};

const PROFILES: ProjectProfiles = { can_manage: true, profiles: [ENFORCED, DEFAULT, OPT_IN] };

const meta: Meta<typeof ProjectProfilesPanel> = {
  title: "Modules/Governance/ProjectProfilesPanel",
  component: ProjectProfilesPanel,
  args: { projectId: PROJECT_ID },
  decorators: [withToast(), withRouter("/")],
};
export default meta;

type Story = StoryObj<typeof ProjectProfilesPanel>;

/** Each profile shows its mode and what it does for the project; an Enforced profile has no choice. */
export const ListsProfiles: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(PROFILES);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("table", { name: "Governance profiles that reach this project" })).toBeInTheDocument());
    await expect(canvas.getByText("Safety critical")).toBeInTheDocument();
    await expect(canvas.getByText("Applies by default")).toBeInTheDocument();
    await expect(canvas.getByText("Available to opt in")).toBeInTheDocument();
    await expect(canvas.getByRole("switch", { name: "Standard review applies to this project" })).toHaveAttribute("aria-checked", "true");
    await expect(canvas.getByRole("switch", { name: "Audit ready applies to this project" })).toHaveAttribute("aria-checked", "false");
    await expect(canvas.queryByRole("switch", { name: "Safety critical applies to this project" })).toBeNull();
  },
};

/** Turning off a Default profile records an opt-out. */
export const OptsOutOfADefaultProfile: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(PROFILES);
    spyOn(api, "put").mockResolvedValue({
      ...PROFILES,
      profiles: [ENFORCED, { ...DEFAULT, outcome: "opted_out", applies: false, choice: false }, OPT_IN],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("switch", { name: "Standard review applies to this project" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${URL}/p-2/choice`, { opted_in: false }));
    await waitFor(() => expect(canvas.getByRole("switch", { name: "Standard review applies to this project" })).toHaveAttribute("aria-checked", "false"));
    await expect(canvas.getByText("Opted out")).toBeInTheDocument();
    await expect(await within(document.body).findByText("The choice for Standard review is saved.")).toBeInTheDocument();
  },
};

/** Turning on an Opt-in profile records an opt-in. */
export const OptsInToAProfile: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(PROFILES);
    spyOn(api, "put").mockResolvedValue({
      ...PROFILES,
      profiles: [ENFORCED, DEFAULT, { ...OPT_IN, outcome: "opted_in", applies: true, choice: true }],
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("switch", { name: "Audit ready applies to this project" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${URL}/p-3/choice`, { opted_in: true }));
    await expect(await canvas.findByText("Opted in")).toBeInTheDocument();
  },
};

/** A person without the right to manage governance sees the choices but cannot change them. */
export const ReadOnly: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ ...PROFILES, can_manage: false });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("switch", { name: "Standard review applies to this project" })).toBeDisabled();
    await expect(canvas.getByRole("switch", { name: "Audit ready applies to this project" })).toBeDisabled();
  },
};

/** A refused change shows the server's message and keeps the stored choice. */
export const SaveFailureShowsAnError: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(PROFILES);
    spyOn(api, "put").mockRejectedValue(new Error("This choice is not allowed."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("switch", { name: "Standard review applies to this project" }));
    await expect(await within(document.body).findByText("This choice is not allowed.")).toBeInTheDocument();
    await expect(canvas.getByRole("switch", { name: "Standard review applies to this project" })).toHaveAttribute("aria-checked", "true");
  },
};

/** No profile reaches the project. */
export const Empty: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ can_manage: true, profiles: [] });
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No governance profile reaches this project.")).toBeInTheDocument();
  },
};

/** A failed read offers Retry. */
export const LoadFailure: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("down"));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("The governance profiles could not be loaded.")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...ListsProfiles, globals: { theme: "dark" } };

/** Long names and descriptions keep every column and switch aligned. The first mounted panel reads the short data, the second the long. */
export const LongText: Story = {
  beforeEach: () => {
    let reads = 0;
    spyOn(api, "get").mockImplementation(async () => {
      const long = reads++ > 0;
      return {
        ...PROFILES,
        profiles: PROFILES.profiles.map((p, index) => ({
          ...p, name: index < 2 ? stressText(long, p.name) : p.name, description: stressText(long, p.description, "summary"),
        })),
      };
    });
  },
  render: () => <TextStress render={() => <ProjectProfilesPanel projectId={PROJECT_ID} />} />,
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getAllByRole("table")).toHaveLength(2));
    await expectStressStable(canvasElement);
  },
};
