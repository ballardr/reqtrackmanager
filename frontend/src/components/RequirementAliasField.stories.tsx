import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { useState } from "react";

import type { PlacementPair } from "../api/placements";
import {
  ALIAS_PROJECT_ID, buildAliasSettings, buildAliasesApi, buildTreeApi,
} from "../testing/requirementAliasFixtures";
import { RequirementAliasField } from "./RequirementAliasField";

/**
 * The create form's "Additional components" field: further categories the new requirement also sits in, each given a
 * code of its own on save. It is absent when the project disallows new aliases or has no other category to offer.
 */
const meta: Meta<typeof RequirementAliasField> = {
  title: "Components/RequirementAliasField",
  component: RequirementAliasField,
  args: { projectId: ALIAS_PROJECT_ID, ownCategoryId: "k-perf", value: [], onChange: fn(), api: buildAliasesApi(), placementsApi: buildTreeApi() },
};
export default meta;

type Story = StoryObj<typeof RequirementAliasField>;

function Controlled(args: Parameters<typeof RequirementAliasField>[0]) {
  const [value, setValue] = useState<PlacementPair[]>([]);
  return <RequirementAliasField {...args} value={value} onChange={(next) => { setValue(next); args.onChange(next); }} />;
}

export const ChoosingFurtherPlaces: Story = {
  render: (args) => <Controlled {...args} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Components and categories" }));
    const body = within(document.body);
    // A component is a heading to open: only a category can be chosen, and the requirement's own category is not offered.
    await expect(await body.findByRole("checkbox", { name: "Hardware" })).toBeDisabled();
    await expect(body.queryByRole("checkbox", { name: "Software / Performance" })).not.toBeInTheDocument();
    await userEvent.click(await body.findByRole("checkbox", { name: "Hardware / Cooling" }));
    await waitFor(() => expect(args.onChange).toHaveBeenLastCalledWith([{ component_id: "c-hw", category_id: "k-cool" }]));
  },
};

export const AbsentWhenNewAliasesAreDisabled: Story = {
  args: { api: buildAliasesApi(buildAliasSettings({ mode: "disabled", source: "project", own_mode: "disabled" })) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.settings).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("button", { name: "Components and categories" })).not.toBeInTheDocument();
  },
};

export const ExplainsItselfInAHelpTooltip: Story = {
  render: (args) => <Controlled {...args} />,
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("button", { name: "Help: Additional components" })).toBeInTheDocument();
  },
};
