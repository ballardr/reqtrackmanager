import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { PolicyAcceptanceStatus } from "../api/types";
import { withToast } from "../testing/storybook-helpers";
import { PolicyAcceptancesDialog } from "./PolicyAcceptancesDialog";

const PATH = "/api/v1/orgs/org-1/policies/nda-1";

const STATUS: PolicyAcceptanceStatus = {
  policy_id: "nda-1", title: "Confidentiality agreement", version: 2, requires_acknowledgement: true, required: 3, accepted: 1, truncated: false,
  people: [
    { user_id: "u2", display_name: "Bo Nguyen", email: "bo@example.com", accepted_version: null, accepted_at: null, current: false },
    { user_id: "u3", display_name: "Cy Ortiz", email: "cy@example.com", accepted_version: 1, accepted_at: "2026-11-01T01:00:00Z", current: false },
    { user_id: "u1", display_name: "Ana Lee", email: "ana@example.com", accepted_version: 2, accepted_at: "2026-11-09T01:00:00Z", current: true },
  ],
};

/** Who has accepted a policy that requires it: counts, then each person with their latest acceptance. */
const meta: Meta<typeof PolicyAcceptancesDialog> = {
  title: "Components/PolicyAcceptancesDialog",
  component: PolicyAcceptancesDialog,
  decorators: [withToast()],
  args: { path: PATH, title: "Confidentiality agreement", onClose: () => undefined },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(STATUS);
  },
};
export default meta;

type Story = StoryObj<typeof PolicyAcceptancesDialog>;

/** The summary counts the current version and each person shows accepted, an earlier version, or not accepted. */
export const ListsEveryPersonWithTheirStatus: Story = {
  play: async () => {
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(await dialog.findByText("1 of 3 accepted version 2.")).toBeInTheDocument();
    await expect(dialog.getByText("Accepted")).toBeInTheDocument();
    await expect(dialog.getByText("Earlier version")).toBeInTheDocument();
    await expect(dialog.getByText("Not accepted")).toBeInTheDocument();
    await expect(dialog.getByText("bo@example.com")).toBeInTheDocument();
    await expect(api.get).toHaveBeenCalledWith(`${PATH}/acknowledgements`);
  },
};

/** A reminder is confirmed first, then sent, and the result says how many people were told. */
export const ARemindIsConfirmedThenSent: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(STATUS);
    spyOn(api, "post").mockResolvedValue({ notified: 2 });
  },
  play: async () => {
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.click(await dialog.findByRole("button", { name: "Send reminder" }));
    await waitFor(async () => expect(await within(document.body).findAllByRole("dialog")).toHaveLength(2));
    const confirm = within((await within(document.body).findAllByRole("dialog"))[1]);
    await expect(confirm.getByText(/except you/)).toBeInTheDocument();
    await userEvent.click(confirm.getByRole("button", { name: "Send reminder" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${PATH}/acknowledgements/remind`, {}));
    await expect(await within(document.body).findByText("2 people notified.")).toBeInTheDocument();
  },
};

/** When everyone has accepted there is nobody to remind. */
export const NoReminderWhenEveryoneAccepted: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ ...STATUS, accepted: 3 });
  },
  play: async () => {
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(await dialog.findByRole("button", { name: "Send reminder" })).toBeDisabled();
  },
};

/** A long list says it is cut and points to the export. */
export const ALongListPointsToTheExport: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ ...STATUS, truncated: true });
  },
  play: async () => {
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(await dialog.findByText("Showing the first 3 people. Export the list for everyone.")).toBeInTheDocument();
  },
};
