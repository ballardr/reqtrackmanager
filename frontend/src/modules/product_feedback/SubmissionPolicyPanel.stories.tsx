import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { PROJECT_ID } from "./requestFixtures";
import { SubmissionPolicyPanel } from "./SubmissionPolicyPanel";

const meta: Meta<typeof SubmissionPolicyPanel> = {
  title: "Modules/ProductFeedback/SubmissionPolicyPanel",
  component: SubmissionPolicyPanel,
  args: { projectId: PROJECT_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof SubmissionPolicyPanel>;

/** Changing the setting saves at once and says so. */
export const ChangingTheSettingSavesAndConfirms: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ submission_policy: "members" });
    spyOn(api, "put").mockResolvedValue({ submission_policy: "triagers" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByLabelText("Who can submit a request");
    await expect(select).toHaveValue("members");
    await userEvent.selectOptions(select, "triagers");
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(expect.stringContaining("/product_feedback/settings"), { submission_policy: "triagers" }));
    await expect(await within(document.body).findByText("Submission setting saved.")).toBeInTheDocument();
    await expect(select).toHaveValue("triagers");
  },
};
