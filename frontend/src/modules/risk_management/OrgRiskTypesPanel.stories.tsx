import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { OrgTypeRow } from "../../components/TypeVocabularyPanels";
import { withToast } from "../../testing/storybook-helpers";
import { OrgRiskTypesPanel } from "./OrgRiskTypesPanel";

const ORG_ID = "org-1";
const URL = `/api/v1/orgs/${ORG_ID}/modules/risk_management/risk-types`;

const DEFAULTS: OrgTypeRow[] = [
  { id: "t1", name: "Safety", is_active: true },
  { id: "t2", name: "Schedule", is_active: true },
];

const meta: Meta<typeof OrgRiskTypesPanel> = {
  title: "Modules/RiskManagement/OrgRiskTypesPanel",
  component: OrgRiskTypesPanel,
  args: { orgId: ORG_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof OrgRiskTypesPanel>;

export const ListsTypes: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(DEFAULTS);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Safety")).toBeInTheDocument());
    await expect(canvas.getByDisplayValue("Schedule")).toBeInTheDocument();
  },
};

export const AddTypeUsesTheRiskEndpoint: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(DEFAULTS);
    spyOn(api, "post").mockResolvedValue({ id: "t3", name: "Cost", is_active: true });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await canvas.findByPlaceholderText("Risk type name"), "Cost");
    await userEvent.click(canvas.getByRole("button", { name: "Add Risk type" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(URL, { name: "Cost" }));
  },
};

export const DarkTheme: Story = { ...ListsTypes, globals: { theme: "dark" } };
