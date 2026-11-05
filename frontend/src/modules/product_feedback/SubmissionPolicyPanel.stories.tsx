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
    spyOn(api, "get").mockResolvedValue({ submission_policy: "members", request_page_sections: null });
    spyOn(api, "put").mockResolvedValue({ submission_policy: "triagers", request_page_sections: null });
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

/** The project's default section order saves on each move and can be reset to the built-in one. */
export const TheDefaultSectionOrderSavesAndResets: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ submission_policy: "members", request_page_sections: null });
    spyOn(api, "put").mockImplementation(async (_path: string, body: unknown) => ({
      submission_policy: "members", request_page_sections: (body as { request_page_sections: string[] | null }).request_page_sections,
    }) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const reset = await canvas.findByRole("button", { name: "Use the built-in order" });
    await expect(reset).toBeDisabled();
    await userEvent.click(canvas.getByRole("button", { name: "Move Demand up" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      expect.stringContaining("/product_feedback/settings"),
      { request_page_sections: ["details", "references", "demand", "scoring", "loop", "versions", "evidence", "comments"] },
    ));
    await waitFor(() => expect(reset).toBeEnabled());
    await userEvent.click(reset);
    await waitFor(() => expect(api.put).toHaveBeenLastCalledWith(expect.stringContaining("/product_feedback/settings"), { request_page_sections: null }));
    await waitFor(() => expect(reset).toBeDisabled());
  },
};
