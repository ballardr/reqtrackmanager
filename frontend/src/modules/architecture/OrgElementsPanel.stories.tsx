import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withAuth, withToast } from "../../testing/storybook-helpers";
import { buildUser } from "../../testing/storybook-helpers";
import { buildElement, mockArchitectureReads, ORG_ID } from "./architectureFixtures";
import { OrgElementsPanel } from "./OrgElementsPanel";

const ORG_ELEMENT = buildElement({ id: "oel-1", project_id: null, organization_id: ORG_ID, unique_code: "ELM-001", name: "Identity service", ports: [] });

const meta: Meta<typeof OrgElementsPanel> = {
  title: "Modules/Architecture/OrgElementsPanel",
  component: OrgElementsPanel,
  args: { orgId: ORG_ID },
  decorators: [withAuth(buildUser({ id: "user-1" })), withToast()],
  beforeEach: () => {
    const get = mockArchitectureReads({ elements: [ORG_ELEMENT] });
    return () => get.mockRestore();
  },
};
export default meta;

type Story = StoryObj<typeof OrgElementsPanel>;

export const ListsTheOrganisationsOwnElements: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Organisation elements" });
    await expect(within(table).getByText("Identity service")).toBeInTheDocument();
    await expect(within(table).getByRole("button", { name: "Retire" })).toBeInTheDocument();
  },
};

/** An organisation element has no project, so its form offers no links or tags and is created without them. */
export const NewElementIsCreatedAtOrganisationLevel: Story = {
  beforeEach: () => {
    const get = mockArchitectureReads({ elements: [ORG_ELEMENT] });
    const post = spyOn(api, "post").mockResolvedValue(ORG_ELEMENT as never);
    return () => { get.mockRestore(); post.mockRestore(); };
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "New element" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Name"), "Message bus");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/architecture/elements`, expect.objectContaining({ name: "Message bus", activate: false }),
    ));
  },
};

export const CollectionsTabManagesSharing: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("tab", { name: "Collections" }));
    await expect(await canvas.findByRole("region", { name: "Shared infrastructure" })).toBeInTheDocument();
  },
};
