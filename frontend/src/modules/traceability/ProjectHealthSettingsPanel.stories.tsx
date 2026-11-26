import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { OrgUser } from "../../api/types";
import { withToast } from "../../testing/storybook-helpers";
import { ProjectHealthSettingsPanel } from "./ProjectHealthSettingsPanel";
import type { HealthSettings } from "./types";

const PROJECT_ID = "project-1";
const URL = `/api/v1/projects/${PROJECT_ID}/modules/traceability/health/settings`;
const OPTIONS = [1, 6, 12, 24, 48, 72, 120, 168, 240, 336];

const USERS: OrgUser[] = [
  {
    user_id: "user-1", email: "alex@example.com", display_name: "Alex Morgan", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
  {
    user_id: "user-2", email: "sam@example.com", display_name: "Sam Rivera", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

const INHERITING: HealthSettings = {
  can_manage: true, mode: "on_demand", mode_source: "organization", interval_hours: 24, interval_source: "default",
  own_mode: null, own_interval_hours: null, organization_mode: "on_demand", organization_interval_hours: 24,
  checks_runner: null, runner_problem: null, interval_options: OPTIONS, on_demand_record_limit: 300, checks_enabled: true,
};

function mockReads(settings: HealthSettings) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === URL) return settings;
    if (path === `/api/v1/projects/${PROJECT_ID}`) return { id: PROJECT_ID, organization_id: "org-1" };
    if (path === "/api/v1/orgs/org-1/users") return USERS;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ProjectHealthSettingsPanel> = {
  title: "Modules/Governance/ProjectHealthSettingsPanel",
  component: ProjectHealthSettingsPanel,
  args: { projectId: PROJECT_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ProjectHealthSettingsPanel>;

/** A project that sets nothing shows the organisation's default as the first option and says where each value comes from. */
export const FollowsTheOrganisation: Story = {
  beforeEach: () => mockReads(INHERITING),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const mode = await canvas.findByRole("combobox", { name: "Mode" });
    await expect(mode).toHaveValue("");
    await expect(within(mode).getByRole("option", { name: "Organisation default (On demand)" })).toBeInTheDocument();
    await expect(canvas.getByText("Inherited from the organisation")).toBeInTheDocument();
    await expect(canvas.queryByRole("combobox", { name: "Snapshot interval" })).toBeNull();
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
  },
};

/** Choosing an interval snapshot reveals the interval; Save sends the three own values. */
export const SavesTheProjectsOwnChoices: Story = {
  beforeEach: () => {
    mockReads(INHERITING);
    spyOn(api, "put").mockResolvedValue({
      ...INHERITING, mode: "snapshot_interval", mode_source: "project", own_mode: "snapshot_interval", interval_hours: 168,
      interval_source: "project", own_interval_hours: 168, checks_runner: { id: "user-2", name: "Sam Rivera" },
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Mode" }), "snapshot_interval");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Snapshot interval" }), "168");
    await userEvent.type(canvas.getByRole("combobox", { name: "Baseline check runner" }), "Sam");
    await userEvent.click(await within(document.body).findByRole("option", { name: /Sam Rivera/ }));
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(URL, { mode: "snapshot_interval", interval_hours: 168, checks_runner_id: "user-2" }));
    await expect(await within(document.body).findByText("The governance health settings are saved.")).toBeInTheDocument();
    await expect(await canvas.findByText("Sam Rivera")).toBeInTheDocument();
    await expect(canvas.getAllByText("Set by this project").length).toBeGreaterThan(0);
  },
};

/** Choosing the organisation default again sends `null` for the mode. */
export const ReturnsToTheOrganisationDefault: Story = {
  beforeEach: () => {
    mockReads({
      ...INHERITING, mode: "snapshot_on_change", mode_source: "project", own_mode: "snapshot_on_change",
      checks_runner: { id: "user-1", name: "Alex Morgan" },
    });
    spyOn(api, "put").mockResolvedValue(INHERITING);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Mode" }), "");
    await userEvent.click(canvas.getByRole("button", { name: "Remove the baseline check runner" }));
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(URL, { mode: null, interval_hours: null, checks_runner_id: null }));
  },
};

/** A runner who can no longer run the checks is flagged beside the field. */
export const FlagsAnUnavailableRunner: Story = {
  beforeEach: () => mockReads({ ...INHERITING, checks_runner: { id: "user-1", name: "Alex Morgan" }, runner_problem: "The person no longer has a role in this project." }),
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("The person no longer has a role in this project.")).toBeInTheDocument();
  },
};

/** A person who cannot manage the project's governance sees the settings but cannot change them. */
export const ReadOnly: Story = {
  beforeEach: () => mockReads({ ...INHERITING, can_manage: false, own_mode: "snapshot_interval", mode: "snapshot_interval", mode_source: "project" }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("combobox", { name: "Mode" })).toBeDisabled();
    await expect(canvas.getByRole("combobox", { name: "Snapshot interval" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Save" })).toBeDisabled();
    await expect(canvas.queryByRole("combobox", { name: "Baseline check runner" })).toBeNull();
  },
};

/** A refused save shows the server's message beside Save. */
export const SaveFailureShowsAnError: Story = {
  beforeEach: () => {
    mockReads(INHERITING);
    spyOn(api, "put").mockRejectedValue(new Error("The baseline check runner is not valid."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Mode" }), "snapshot_on_change");
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await expect(await canvas.findByText("The baseline check runner is not valid.")).toBeInTheDocument();
  },
};

/** A failed read offers Retry. */
export const LoadFailure: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("down"));
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("The governance health settings could not be loaded.")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...FollowsTheOrganisation, globals: { theme: "dark" } };
