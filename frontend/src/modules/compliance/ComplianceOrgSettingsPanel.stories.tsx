import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import type { OrgGroup } from "../../api/types";
import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { ComplianceOrgSettingsPanel } from "./ComplianceOrgSettingsPanel";
import type { ComplianceOrgSettings } from "./types";

const ORG_ID = "org-1";

const GROUPS: OrgGroup[] = [
  { id: "group-1", name: "Compliance Managers", member_user_ids: ["user-1"], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
  { id: "group-2", name: "Security Team", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];

function mockSettingsApi(initial: ComplianceOrgSettings) {
  let settings = initial;
  spyOn(api, "get").mockImplementation(async (path: string) =>
    path.endsWith("/groups") ? GROUPS : settings
  );
  spyOn(api, "put").mockImplementation(async (_path: string, body?: unknown) => {
    settings = { ...settings, ...(body as ComplianceOrgSettings) };
    return settings;
  });
}

const meta: Meta<typeof ComplianceOrgSettingsPanel> = {
  title: "Modules/Compliance/ComplianceOrgSettingsPanel",
  component: ComplianceOrgSettingsPanel,
  args: { orgId: ORG_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ComplianceOrgSettingsPanel>;

export const NoFallbackGroupConfigured: Story = {
  beforeEach: () => mockSettingsApi({ default_standards_manager_group_id: null }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByLabelText("Default compliance-managers group");
    await waitFor(() => expect(select).toHaveValue(""));
  },
};

export const FallbackGroupAlreadyConfigured: Story = {
  beforeEach: () => mockSettingsApi({ default_standards_manager_group_id: "group-1" }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByLabelText("Default compliance-managers group");
    await waitFor(() => expect(select).toHaveValue("group-1"));
  },
};

export const ChangingTheSelectionSaves: Story = {
  beforeEach: () => mockSettingsApi({ default_standards_manager_group_id: null }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByLabelText("Default compliance-managers group");
    await userEvent.selectOptions(select, "group-2");

    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/settings`,
      { default_standards_manager_group_id: "group-2" }
    ));
  },
};

export const LightTheme: Story = { ...NoFallbackGroupConfigured };
export const DarkTheme: Story = { ...NoFallbackGroupConfigured, globals: { theme: "dark" } };
