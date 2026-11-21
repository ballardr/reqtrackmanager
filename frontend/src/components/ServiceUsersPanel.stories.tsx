import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildServiceUser, buildToken, ORG_ID, SERVICE_USERS } from "../testing/serviceUserFixtures";
import { withRouter, withToast } from "../testing/storybook-helpers";
import { ServiceUsersPanel } from "./ServiceUsersPanel";

/** The organisation's service users for its administrators: a sortable list, a create form and a detail dialog per service user. */
const meta: Meta<typeof ServiceUsersPanel> = {
  title: "Components/ServiceUsersPanel",
  component: ServiceUsersPanel,
  decorators: [withToast(), withRouter("/orgs/org-1/admin/service-users")],
  args: { organizationId: ORG_ID },
};
export default meta;

type Story = StoryObj<typeof ServiceUsersPanel>;

function mockApis(users = SERVICE_USERS, tokens = [buildToken()]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.startsWith("/api/v1/me/pats/max-lifetime")) return { max_expires_at: "2027-02-01T00:00:00Z" };
    if (path.includes("/pats")) return tokens;
    if (path.startsWith("/api/v1/projects")) return [{ id: "p-1", name: "Falcon", organization_id: ORG_ID }];
    return users;
  });
}

/** Nothing yet: the empty state says what a service user is for. */
export const Empty: Story = {
  beforeEach: () => mockApis([]),
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText(/No service users yet/)).toBeInTheDocument();
  },
};

/** Each row names its responsible party, shows the review flags with their meaning, the token count and the state. */
export const ListsServiceUsersWithFlags: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Service users" });
    await expect(within(table).getByText("Build agent")).toBeInTheDocument();
    await expect(within(table).getAllByText("Platform team")[0]).toBeInTheDocument();
    await expect(within(table).getByText("No responsible party")).toBeInTheDocument();
    await expect(within(table).getByText("Administrator rights")).toBeInTheDocument();
    await expect(within(table).getByText("Deactivated")).toBeInTheDocument();
    await expect(within(table).getAllByText("Service")).toHaveLength(3);
  },
};

/** The Name header sorts the list, and the order is the one in the URL. */
export const NameHeaderSorts: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Service users" });
    await userEvent.click(canvas.getByRole("button", { name: /^Name/ }));
    const firstRow = () => within(canvas.getAllByRole("row")[1]).getAllByRole("cell")[0];
    await expect(firstRow()).toHaveTextContent("Build agent");
    await userEvent.click(canvas.getByRole("button", { name: /^Name/ }));
    await expect(firstRow()).toHaveTextContent("Retired job");
  },
};

/** Creating sends only the fields given, then reloads and confirms with a Toast. */
export const CreatingSendsTheDraft: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "post").mockResolvedValue(buildServiceUser({ user_id: "su-9", name: "New job" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "New service user" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "New service user" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "New job");
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/service-users`, { name: "New job", description: "", responsible: null }),
    );
    await expect(await within(document.body).findByText("Service user created.")).toBeInTheDocument();
  },
};

/** A refused save (a name already in use) stays in the dialog header. */
export const ASaveErrorStaysInTheDialog: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "post").mockRejectedValue(new Error("A service user with this name already exists in this organisation."));
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "New service user" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "New service user" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Build agent");
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await expect(await dialog.findByText(/already exists/)).toBeInTheDocument();
  },
};

/** Issuing a token shows its secret once, with the warning; dismissing removes it. */
export const IssuingATokenShowsTheSecretOnce: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "post").mockResolvedValue({ ...buildToken({ id: "tok-2", name: "Deploy" }), token: "rtm_pat_one_time_secret", notice: "This token is shown once. Copy it now: it cannot be retrieved again." });
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: /^Build agent/ }));
    const detail = within(await within(document.body).findByRole("dialog", { name: "Service user: Build agent" }));
    await userEvent.click(await detail.findByRole("button", { name: "Issue token" }));
    const form = within(await within(document.body).findByRole("dialog", { name: "Issue token" }));
    await waitFor(() => expect(form.getByLabelText("Expiry date")).toHaveValue("2027-02-01"));
    await userEvent.type(form.getByRole("textbox", { name: "Token name" }), "Deploy");
    await userEvent.click(form.getByRole("checkbox", { name: "Falcon" }));
    await userEvent.click(form.getByRole("button", { name: "Issue token" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/orgs/${ORG_ID}/service-users/su-1/pats`,
        expect.objectContaining({ name: "Deploy", allowed_project_ids: ["p-1"] }),
      ),
    );
    await expect(await detail.findByText("rtm_pat_one_time_secret")).toBeInTheDocument();
    await expect(detail.getByText(/shown once/)).toBeInTheDocument();
    await userEvent.click(detail.getByRole("button", { name: "I have copied it" }));
    await expect(detail.queryByText("rtm_pat_one_time_secret")).not.toBeInTheDocument();
  },
};

/** Revoking a token asks first, then calls the endpoint and confirms with a Toast. */
export const RevokingATokenAsksFirst: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: /^Build agent/ }));
    const detail = within(await within(document.body).findByRole("dialog", { name: "Service user: Build agent" }));
    await userEvent.click(await detail.findByRole("button", { name: "Revoke the token Nightly" }));
    const confirm = within(await within(document.body).findByRole("dialog", { name: "Revoke this token?" }));
    await userEvent.click(confirm.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/service-users/su-1/pats/tok-1`));
    await expect(await within(document.body).findByText("Token revoked.")).toBeInTheDocument();
  },
};

/** Deactivating asks first; archiving a deactivated service user needs its name typed. */
export const ArchiveNeedsTheNameTyped: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: /^Retired job/ }));
    const detail = within(await within(document.body).findByRole("dialog", { name: "Service user: Retired job" }));
    await expect(detail.getByRole("button", { name: "Reactivate" })).toBeInTheDocument();
    await userEvent.click(detail.getByRole("button", { name: "Archive" }));
    const confirm = within(await within(document.body).findByRole("dialog", { name: "Archive Retired job?" }));
    const archive = confirm.getByRole("button", { name: "Archive" });
    await expect(archive).toBeDisabled();
    await userEvent.type(confirm.getByRole("textbox"), "Retired job");
    await expect(archive).toBeEnabled();
    await userEvent.click(archive);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/users/su-3/archive`));
  },
};
