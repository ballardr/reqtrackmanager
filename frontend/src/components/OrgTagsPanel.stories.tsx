import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, within } from "storybook/test";

import { api } from "../api/client";
import { buildUsage, buildVocabulary } from "../testing/tagsFixtures";
import { withToast } from "../testing/storybook-helpers";
import { OrgTagsPanel } from "./OrgTagsPanel";

/** Org Admin's Tags section: the tag admin bound to the organisation's own vocabulary (organisation-owned records). */
const meta: Meta<typeof OrgTagsPanel> = {
  title: "Components/OrgTagsPanel",
  component: OrgTagsPanel,
  decorators: [withToast()],
  args: { organizationId: "org-1" },
};
export default meta;

type Story = StoryObj<typeof OrgTagsPanel>;

export const ReadsTheOrganisationsVocabularyWithNoParentToFollow: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/orgs/org-1/tags") return buildVocabulary({ own_mode: null });
      if (path === "/api/v1/orgs/org-1/tags/usage") return buildUsage();
      throw new Error(`unmocked path: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("table", { name: "Tags" })).toBeInTheDocument();
    await expect(canvas.getByText(/records the organisation owns/)).toBeInTheDocument();
    await expect(canvas.queryByRole("option", { name: "Follow the parent project" })).not.toBeInTheDocument();
  },
};
