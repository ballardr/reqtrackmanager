import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgStorage } from "../api/types";
import { withToast } from "../testing/storybook-helpers";
import { OrgStorageDialog } from "./OrgStorageDialog";

const STORAGE: OrgStorage = {
  file_uploads_enabled: true, deployment_uploads_enabled: true, storage_quota_bytes: 2 * 1024 ** 3,
  default_storage_quota_bytes: 10 * 1024 ** 3, effective_quota_bytes: 2 * 1024 ** 3, quota_source: "organization",
  used_bytes: 1024 ** 3, file_count: 42, warning: false, can_edit: true,
};

function mockStorage(storage: OrgStorage) {
  spyOn(api, "get").mockResolvedValue(storage);
  spyOn(api, "put").mockResolvedValue(storage);
}

const meta: Meta<typeof OrgStorageDialog> = {
  title: "Components/OrgStorageDialog",
  component: OrgStorageDialog,
  decorators: [withToast()],
  args: { orgId: "org-1", orgName: "Acme Corp", onClose: fn(), onSaved: fn() },
};
export default meta;

type Story = StoryObj<typeof OrgStorageDialog>;

const body = () => within(document.body);

/** The switch, the limit (read back in GB), the usage against the limit and the number of files. */
export const ShowsRulesAndUsage: Story = {
  beforeEach: () => mockStorage(STORAGE),
  play: async () => {
    await expect(await body().findByRole("dialog", { name: "Storage: Acme Corp" })).toBeVisible();
    await expect(await body().findByRole("spinbutton", { name: "Storage limit" })).toHaveValue(2);
    await expect(body().getByRole("combobox", { name: "Storage limit unit" })).toHaveValue("GB");
    await expect(body().getByRole("progressbar", { name: "1.0 GB of 2.0 GB (50%)" })).toBeVisible();
    await expect(body().getByText("42")).toBeVisible();
  },
};

/** Changing the switch and the limit and saving sends the bytes and closes the dialog. */
export const SaveSendsTheRules: Story = {
  beforeEach: () => mockStorage(STORAGE),
  play: async ({ args }) => {
    const limit = await body().findByRole("spinbutton", { name: "Storage limit" });
    await userEvent.clear(limit);
    await userEvent.type(limit, "512");
    await userEvent.selectOptions(body().getByRole("combobox", { name: "Storage limit unit" }), "MB");
    await userEvent.click(body().getByRole("switch", { name: "Allow file uploads" }));
    await userEvent.click(body().getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/orgs/org-1/storage", {
      file_uploads_enabled: false, storage_quota_bytes: 512 * 1024 ** 2,
    }));
    await waitFor(() => expect(args.onClose).toHaveBeenCalled());
  },
};

/** An empty limit follows the server default, and the placeholder says what that is. */
export const EmptyLimitFollowsTheServerDefault: Story = {
  beforeEach: () => mockStorage({ ...STORAGE, storage_quota_bytes: null, effective_quota_bytes: 10 * 1024 ** 3, quota_source: "server" }),
  play: async () => {
    const limit = await body().findByRole("spinbutton", { name: "Storage limit" });
    await expect(limit).toHaveAttribute("placeholder", "Server default (10.0 GB)");
    await userEvent.click(body().getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/orgs/org-1/storage", {
      file_uploads_enabled: true, storage_quota_bytes: null,
    }));
  },
};

/** While the deployment-wide switch is off the dialog says it takes precedence. */
export const DeploymentSwitchOff: Story = {
  beforeEach: () => mockStorage({ ...STORAGE, deployment_uploads_enabled: false }),
  play: async () => {
    await expect(await body().findByText(/disabled for the whole deployment/)).toBeVisible();
  },
};

/** A caller who may only read sees the figures with the controls unavailable and no Save. */
export const ReadOnly: Story = {
  beforeEach: () => mockStorage({ ...STORAGE, can_edit: false }),
  play: async () => {
    await expect(await body().findByRole("spinbutton", { name: "Storage limit" })).toBeDisabled();
    await expect(body().getByRole("switch", { name: "Allow file uploads" })).toBeDisabled();
    await expect(body().queryByRole("button", { name: "Save" })).toBeNull();
    await expect(body().getByText(/Only a server administrator or a Platform subscription manager/)).toBeVisible();
  },
};

/** A failed read says so instead of showing empty fields. */
export const LoadFailure: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("boom"));
  },
  play: async () => {
    await expect(await body().findByText("Could not load the storage rules.")).toBeVisible();
  },
};
