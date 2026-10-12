import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { PROJECT_ID, RISK_TYPES } from "./riskFixtures";
import { ProjectRiskTypesPanel } from "./ProjectRiskTypesPanel";

const URL = `/api/v1/projects/${PROJECT_ID}/modules/risk_management/risk-types`;

const meta: Meta<typeof ProjectRiskTypesPanel> = {
  title: "Modules/RiskManagement/ProjectRiskTypesPanel",
  component: ProjectRiskTypesPanel,
  args: { projectId: PROJECT_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ProjectRiskTypesPanel>;

export const ListsEffectiveTypes: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(RISK_TYPES);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Safety")).toBeInTheDocument());
    await expect(canvas.getAllByText("Org default")).toHaveLength(2);
  },
};

export const AddLocalTypeUsesTheRiskEndpoint: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(RISK_TYPES);
    spyOn(api, "post").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await canvas.findByPlaceholderText("Project Risk type name"), "Regulatory");
    await userEvent.click(canvas.getByRole("button", { name: "Add project-only Risk type" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(URL, { name: "Regulatory", display_order: 2 }));
  },
};

export const DarkTheme: Story = { ...ListsEffectiveTypes, globals: { theme: "dark" } };
