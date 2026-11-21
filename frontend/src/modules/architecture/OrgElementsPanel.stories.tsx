import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { expectHeaderOrdersText } from "../../testing/sortHelpers";
import { expectTextRows } from "../../testing/menuRows";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildElement, buildFolder, mockArchitectureReads, ORG_ID } from "./architectureFixtures";
import { OrgElementsPanel } from "./OrgElementsPanel";

const ORG_ELEMENT = buildElement({ id: "oel-1", project_id: null, organization_id: ORG_ID, unique_code: "ELM-001", name: "Identity service", ports: [] });

const meta: Meta<typeof OrgElementsPanel> = {
  title: "Modules/Architecture/OrgElementsPanel",
  component: OrgElementsPanel,
  args: { orgId: ORG_ID },
  decorators: [withAuth(buildUser({ id: "user-1" })), withRouter("/"), withToast()],
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
    // One actions menu per row, never a row of buttons.
    await expect(within(table).getAllByRole("button").filter((b) => /^(Edit|Archive|Change status)/.test(b.textContent ?? ""))).toHaveLength(0);
    await userEvent.click(within(table).getByRole("button", { name: "Actions for Identity service" }));
    const menu = within(await within(document.body).findByRole("menu"));
    await expect(menu.getByRole("menuitem", { name: "Edit" })).toBeVisible();
    await expect(menu.getByRole("menuitem", { name: "Archive" })).toBeVisible();
    // The first parent row ("Change status") starts open, listing the server's allowed moves.
    await expect(await menu.findByRole("menuitem", { name: /^Move from / })).toBeVisible();
    await expectTextRows(within(document.body).getByRole("menu"));
  },
};

/** One primary button and one actions menu above the list: folders first, then Export and Import. */
export const HeaderHasOnePrimaryButtonAndOneActionsMenu: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Organisation elements" });
    await expect(canvas.getByRole("button", { name: "New element" })).toBeVisible();
    await expect(canvas.queryByRole("button", { name: "New folder" })).toBeNull();
    await userEvent.click(canvas.getByRole("button", { name: "List actions" }));
    const menu = within(await within(document.body).findByRole("menu"));
    await expect(menu.getByRole("menuitem", { name: "New folder" })).toBeVisible();
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

/** The organisation's element folders: a Folder column, and choosing a folder narrows the table to it. */
export const FolderColumnAndPanelNarrowTheTable: Story = {
  beforeEach: () => {
    const get = mockArchitectureReads({
      elements: [
        buildElement({ ...ORG_ELEMENT, folder_id: "of-1", folder_path: "Platform" }),
        buildElement({ ...ORG_ELEMENT, id: "oel-2", unique_code: "ELM-002", name: "Message bus", folder_id: null, folder_path: null }),
      ],
      folders: [buildFolder({ id: "of-1", project_id: null, organization_id: ORG_ID, name: "Platform", path: "Platform", record_count: 1 })],
    });
    return () => get.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Organisation elements" });
    await expect(within(table).getByText("Platform")).toBeInTheDocument();
    await userEvent.click(await canvas.findByRole("button", { name: "Folder Platform" }));
    await waitFor(() => expect(within(table).queryByText("Message bus")).not.toBeInTheDocument());
    await expect(within(table).getByText("Identity service")).toBeInTheDocument();
  },
};

/** The Name header orders the organisation's elements, ascending then descending. */
export const NameHeaderSortsTheElements: Story = {
  beforeEach: () => {
    const get = mockArchitectureReads({
      elements: [ORG_ELEMENT, buildElement({ ...ORG_ELEMENT, id: "oel-2", unique_code: "ELM-002", name: "Audit log" })],
    });
    return () => get.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const table = await within(canvasElement).findByRole("table", { name: "Organisation elements" });
    await expectHeaderOrdersText(table, "Name");
  },
};