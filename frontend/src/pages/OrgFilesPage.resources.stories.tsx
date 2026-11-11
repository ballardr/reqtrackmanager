import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgResource } from "../api/types";
import { buildUser, withRouter, withStatefulAuth } from "../testing/storybook-helpers";
import { OrgFilesPage } from "./OrgFilesPage";

const ORG_ID = "org-1";

/** The Shared resources tab of the organisation Files page (`?tab=resources`). */
const meta: Meta<typeof OrgFilesPage> = {
  title: "Pages/OrgFilesPage/Shared resources",
  component: OrgFilesPage,
  decorators: [
    withStatefulAuth(buildUser({ ui_preferences: {} })),
    withRouter(`/orgs/${ORG_ID}/files?tab=resources`, "/orgs/:orgId/files"),
  ],
};
export default meta;

type Story = StoryObj<typeof OrgFilesPage>;

function resource(id: string, filename: string, created_at: string, uploader: string, link_count: number): OrgResource {
  return {
    id, organization_id: ORG_ID, filename, content_type: "text/plain", size_bytes: 10, uploaded_by: "user-1",
    is_org_resource: true, confidential: false, created_at, uploaded_by_display_name: uploader, link_count,
  };
}

const RESOURCES: OrgResource[] = [
  resource("r1", "standards.pdf", "2026-08-21T09:00:00Z", "Alex Morgan", 2),
  resource("r2", "glossary.txt", "2026-08-22T09:00:00Z", "Jamie Lee", 0),
];

/** Answers the tab's reads: the resources and the server's answer on whether the person may manage them. */
function mockServer({ rows = RESOURCES, canManage }: { rows?: OrgResource[]; canManage: boolean }) {
  spyOn(api, "postPage").mockResolvedValue({ items: [], total: 0 } as never);
  spyOn(api, "get").mockImplementation((async (path: string) => {
    if (path.endsWith("/resources/access")) return { can_manage: canManage };
    if (path.endsWith("/resources")) return rows;
    if (path.includes("/files/")) return [];
    throw new Error(`unmocked path: ${path}`);
  }) as never);
}

/** A person who manages shared resources sees the upload control and a Delete on every row. */
export const SharedResourcesForAManager: Story = {
  beforeEach: () => {
    mockServer({ canManage: true });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("standards.pdf")).toBeInTheDocument());
    await expect(canvas.getByRole("tab", { name: "Shared resources", selected: true })).toBeInTheDocument();
    await expect(canvas.getByText("Alex Morgan")).toBeInTheDocument();
    await expect(canvas.getByText("Upload shared resource")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Delete glossary.txt" })).toBeInTheDocument();
  },
};

/** Anyone else sees the same list read-only: no upload control and no Actions column. */
export const SharedResourcesForAMember: Story = {
  beforeEach: () => {
    mockServer({ canManage: false });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("standards.pdf")).toBeInTheDocument());
    await expect(canvas.queryByText("Upload shared resource")).toBeNull();
    await expect(canvas.queryByRole("button", { name: /^Delete / })).toBeNull();
  },
};

export const SharedResourcesEmpty: Story = {
  beforeEach: () => {
    mockServer({ rows: [], canManage: true });
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No shared resources have been uploaded yet.")).toBeInTheDocument();
  },
};

/** The search narrows the list by file name in the browser. */
export const SharedResourcesSearch: Story = {
  beforeEach: () => {
    mockServer({ canManage: false });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText("standards.pdf");
    await userEvent.type(canvas.getByRole("textbox", { name: "Search shared resource names" }), "gloss");
    await waitFor(() => expect(canvas.queryByText("standards.pdf")).toBeNull());
    await expect(canvas.getByText("glossary.txt")).toBeInTheDocument();
  },
};

/** Deleting an unlinked resource asks plainly; one with links names them and asks for the file name. */
export const DeletingAResourceStatesItsLinks: Story = {
  beforeEach: () => {
    mockServer({ canManage: true });
    spyOn(api, "delete").mockResolvedValue(undefined as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Delete standards.pdf" }));
    const dialog = within(await within(canvasElement.ownerDocument.body).findByRole("dialog"));
    await expect(dialog.getByText(/removed from 2 requirements/)).toBeInTheDocument();
    await expect(dialog.getByRole("button", { name: "Delete" })).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox"), "standards.pdf");
    await userEvent.click(dialog.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/resources/r1`));
  },
};
