import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildServiceUser, buildToken, ORG_ID } from "../testing/serviceUserFixtures";
import { withRouter, withToast } from "../testing/storybook-helpers";
import { ServiceUserDetailModal } from "./ServiceUserDetailModal";

/** One service user in a dialog: its details, its tokens and the actions an organisation administrator has on it. */
const meta: Meta<typeof ServiceUserDetailModal> = {
  title: "Components/ServiceUserDetailModal",
  component: ServiceUserDetailModal,
  decorators: [withToast(), withRouter("/orgs/org-1/admin/users")],
  args: {
    organizationId: ORG_ID, serviceUser: buildServiceUser(), projects: [{ id: "p-1", name: "Falcon", organization_id: ORG_ID }] as never,
    onEdit: fn(), onChanged: fn(), onClose: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof ServiceUserDetailModal>;

function mockApis(tokens = [buildToken()]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.startsWith("/api/v1/me/pats/max-lifetime")) return { max_expires_at: "2027-02-01T00:00:00Z" };
    if (path.includes("/pats")) return tokens;
    throw new Error(`unmocked path: ${path}`);
  });
}

/** The dialog names the account, marks it Service, lists its tokens with their state and offers the lifecycle actions. */
export const ShowsDetailsAndTokens: Story = {
  beforeEach: () => mockApis(),
  play: async () => {
    const detail = within(await within(document.body).findByRole("dialog", { name: "Service user: Build agent" }));
    await expect(detail.getByText("Runs the nightly import.")).toBeInTheDocument();
    await expect(detail.getByText("Platform team")).toBeInTheDocument();
    await expect(await detail.findByRole("row", { name: /Nightly/ })).toHaveTextContent("Active");
    await expect(detail.getByRole("button", { name: "Deactivate" })).toBeInTheDocument();
  },
};

/** Issuing a token shows its secret once, with the warning; dismissing removes it. */
export const IssuingATokenShowsTheSecretOnce: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "post").mockResolvedValue({ ...buildToken({ id: "tok-2", name: "Deploy" }), token: "rtm_pat_one_time_secret", notice: "This token is shown once. Copy it now: it cannot be retrieved again." });
  },
  play: async ({ args }) => {
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
    await expect(args.onChanged).toHaveBeenCalled();
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
  play: async () => {
    const detail = within(await within(document.body).findByRole("dialog", { name: "Service user: Build agent" }));
    await userEvent.click(await detail.findByRole("button", { name: "Revoke the token Nightly" }));
    const confirm = within(await within(document.body).findByRole("dialog", { name: "Revoke this token?" }));
    await userEvent.click(confirm.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/service-users/su-1/pats/tok-1`));
    await expect(await within(document.body).findByText("Token revoked.")).toBeInTheDocument();
  },
};

/** A deactivated service user can be reactivated; archiving it needs its name typed. */
export const ArchiveNeedsTheNameTyped: Story = {
  args: { serviceUser: buildServiceUser({ user_id: "su-3", name: "Retired job", is_active: false, active_token_count: 0 }) },
  beforeEach: () => {
    mockApis([]);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ args }) => {
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
    await waitFor(() => expect(args.onClose).toHaveBeenCalled());
  },
};
