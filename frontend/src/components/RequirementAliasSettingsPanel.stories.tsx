import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildAliasSettings, buildAliasesApi } from "../testing/requirementAliasFixtures";
import { RequirementAliasSettingsPanel } from "./RequirementAliasSettingsPanel";

/**
 * The requirement alias setting: the organisation's default and a project's own value. A project names where an
 * inherited value came from, counts its aliases and can make them all independent.
 */
const meta: Meta<typeof RequirementAliasSettingsPanel> = {
  title: "Components/RequirementAliasSettingsPanel",
  component: RequirementAliasSettingsPanel,
  args: { scope: { kind: "project", projectId: "project-1" }, api: buildAliasesApi() },
};
export default meta;

type Story = StoryObj<typeof RequirementAliasSettingsPanel>;

export const AProjectNamesWhereTheValueCameFrom: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Inherited from organisation")).toBeInTheDocument();
    await expect(canvas.getByRole("combobox", { name: /New requirement aliases/ })).toHaveValue("inherit");
    await expect(canvas.getByText("1 alias in this project")).toBeInTheDocument();
  },
};

export const SettingAProjectValueAndGoingBack: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: /New requirement aliases/ }), "disabled");
    await waitFor(() => expect(args.api!.setProjectMode).toHaveBeenCalledWith("project-1", "disabled"));
    await userEvent.click(await canvas.findByRole("button", { name: "Use inherited value" }));
    await waitFor(() => expect(args.api!.setProjectMode).toHaveBeenLastCalledWith("project-1", null));
  },
};

export const AnOrganisationChoosesAllowedOrDisabled: Story = {
  args: { scope: { kind: "organization", organizationId: "org-1" } },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByRole("combobox", { name: /New requirement aliases/ });
    await expect(within(select).queryByRole("option", { name: /Follow the parent/ })).not.toBeInTheDocument();
    await userEvent.selectOptions(select, "disabled");
    await waitFor(() => expect(args.api!.setOrganizationMode).toHaveBeenCalledWith("org-1", "disabled"));
  },
};

export const MakingEveryAliasIndependentNeedsTheCountTyped: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Make all independent" }));
    const body = within(document.body);
    const confirm = within(await body.findByRole("dialog")).getByRole("button", { name: "Make all independent" });
    await expect(confirm).toBeDisabled();
    await userEvent.type(await body.findByLabelText('Type "1" to confirm'), "1");
    await userEvent.click(confirm);
    await waitFor(() => expect(args.api!.makeAllIndependent).toHaveBeenCalledWith("project-1"));
  },
};

export const NoBulkActionForAProjectWithoutAliases: Story = {
  args: { api: buildAliasesApi(buildAliasSettings({ alias_count: 0 })) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("This project has no aliases.")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Make all independent" })).not.toBeInTheDocument();
  },
};
