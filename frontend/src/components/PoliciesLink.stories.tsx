import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildPublicPolicy, withRouter } from "../testing/storybook-helpers";
import { PoliciesLink } from "./PoliciesLink";

/** The footer link to the Policies page, shown only when a policy is published. */
const meta: Meta<typeof PoliciesLink> = { title: "Components/PoliciesLink", component: PoliciesLink, decorators: [withRouter("/")] };
export default meta;

type Story = StoryObj<typeof PoliciesLink>;

/** With a published policy the link goes to the page. */
export const ShowsWhenAPolicyIsPublished: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([buildPublicPolicy()]);
  },
  play: async ({ canvasElement }) => {
    const link = await within(canvasElement).findByRole("link", { name: "Policies" });
    await expect(link).toHaveAttribute("href", "/policies");
    await expect(api.get).toHaveBeenCalledWith("/api/v1/public/policies");
  },
};

/** With none published, or when the read fails, nothing is shown. */
export const AbsentWhenNoneIsPublished: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("link")).not.toBeInTheDocument();
  },
};
