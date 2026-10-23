/**
 * Stories for `PersonalDataPolicyPanel` — the personal-data policy for record export and import at the
 * server tier and the organisation tier.
 */
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgRecordSensitivity, ServerRecordSensitivity } from "../api/types";
import { buildUser, withAuth, withToast } from "../testing/storybook-helpers";
import { PersonalDataPolicyPanel } from "./PersonalDataPolicyPanel";

const SERVER_ROWS: ServerRecordSensitivity[] = [
  { tag: "personal", allowed: false },
  { tag: "contact", allowed: true },
  { tag: "free_text_people", allowed: false },
];

const ORG_ROWS: OrgRecordSensitivity[] = [
  { tag: "personal", server_allowed: false, override: null, effective: false },
  { tag: "contact", server_allowed: true, override: false, effective: false },
  { tag: "free_text_people", server_allowed: false, override: null, effective: false },
];

const ORG_URL = "/api/v1/orgs/org-1/record-sensitivity-policy";

const meta: Meta<typeof PersonalDataPolicyPanel> = {
  title: "Components/PersonalDataPolicyPanel",
  component: PersonalDataPolicyPanel,
  decorators: [withAuth(buildUser({ is_server_admin: true })), withToast()],
};
export default meta;

type Story = StoryObj<typeof PersonalDataPolicyPanel>;

/** Server tier: each tag states whether it is allowed; allowing one asks first, excluding one does not. */
export const ServerDefaults: Story = {
  args: { scope: { kind: "server" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(SERVER_ROWS);
    spyOn(api, "put").mockImplementation(async (path: string, body?: unknown) => ({
      tag: path.split("/").pop(), allowed: (body as { allowed: boolean }).allowed,
    }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Contact details")).toBeInTheDocument());
    await expect(canvas.getAllByText("Excluded on this server.")).toHaveLength(2);
    await expect(canvas.getByText("Allowed on this server.")).toBeInTheDocument();

    // Widening: a Tier 1 confirm, nothing is saved until it is accepted.
    await userEvent.click(canvas.getByRole("switch", { name: "Allow names and identifiers in exports and imports" }));
    const dialog = within(document.body).getByRole("dialog");
    await expect(api.put).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Allow" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      "/api/v1/system/record-sensitivity-policy/personal", { allowed: true },
    ));
    await waitFor(() => expect(within(document.body).getByText("Names and identifiers allowed.")).toBeInTheDocument());

    // Narrowing: saved at once.
    await userEvent.click(canvas.getByRole("switch", { name: "Allow contact details in exports and imports" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      "/api/v1/system/record-sensitivity-policy/contact", { allowed: false },
    ));
    await waitFor(() => expect(within(document.body).getByText("Contact details excluded.")).toBeInTheDocument());
  },
};

/** Cancelling the widening confirm leaves the setting untouched. */
export const CancelWidening: Story = {
  args: { scope: { kind: "server" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(SERVER_ROWS);
    spyOn(api, "put").mockResolvedValue({});
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Contact details")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("switch", { name: "Allow free text that can quote people in exports and imports" }));
    await userEvent.click(within(within(document.body).getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    await expect(api.put).not.toHaveBeenCalled();
    await expect(canvas.getByRole("switch", { name: "Allow free text that can quote people in exports and imports" })).not.toBeChecked();
  },
};

/** Organisation tier: the server default is shown beside the organisation's own decision, with a way back. */
export const OrganisationOverride: Story = {
  args: { scope: { kind: "organization", organizationId: "org-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(ORG_ROWS);
    spyOn(api, "put").mockImplementation(async (path: string, body?: unknown) => {
      const tag = path.split("/").pop();
      const row = ORG_ROWS.find((r) => r.tag === tag)!;
      const override = (body as { allowed: boolean | null }).allowed;
      return { ...row, override, effective: override ?? row.server_allowed };
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Contact details")).toBeInTheDocument());
    await expect(canvas.getByText("Server default: allowed. Here: excluded.")).toBeInTheDocument();
    await expect(canvas.getAllByText("Follows the server")).toHaveLength(2);

    // Following the server again would allow the tag here, so it asks first.
    await userEvent.click(canvas.getByRole("button", { name: "Follow the server again" }));
    await userEvent.click(within(within(document.body).getByRole("dialog")).getByRole("button", { name: "Allow" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(ORG_URL + "/contact", { allowed: null }));
    await waitFor(() => expect(canvas.getAllByText("Follows the server")).toHaveLength(3));
  },
};

/** An organisation choice that differs from the server is saved as an override; excluding is not confirmed. */
export const OrganisationDiffersFromServer: Story = {
  args: { scope: { kind: "organization", organizationId: "org-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([
      { tag: "personal", server_allowed: true, override: null, effective: true },
      { tag: "contact", server_allowed: false, override: null, effective: false },
      { tag: "free_text_people", server_allowed: false, override: null, effective: false },
    ] satisfies OrgRecordSensitivity[]);
    spyOn(api, "put").mockResolvedValue({ tag: "personal", server_allowed: true, override: false, effective: false });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Names and identifiers")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("switch", { name: "Allow names and identifiers in exports and imports" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(ORG_URL + "/personal", { allowed: false }));
    await waitFor(() => expect(canvas.getByText("Custom")).toBeInTheDocument());
  },
};
