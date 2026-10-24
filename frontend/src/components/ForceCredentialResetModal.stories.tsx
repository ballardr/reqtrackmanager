import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ForceResetResult } from "../api/types";
import { requiredCaptions } from "../testing/requiredMarkers";
import { withToast } from "../testing/storybook-helpers";
import { ForceCredentialResetModal } from "./ForceCredentialResetModal";

const RESULT: ForceResetResult = {
  accounts: 12, marked: 11, sessions_ended: 12, tokens_revoked: 3, two_factor_cleared: 0,
  without_local_credential: 1, emailed: 11, email_failed: 0,
};

const ORGS = [{ id: "org-1", name: "Acme Corp" }];

function mockApis() {
  spyOn(api, "get").mockResolvedValue(ORGS);
  spyOn(api, "post").mockResolvedValue(RESULT);
}

const meta: Meta<typeof ForceCredentialResetModal> = {
  title: "Components/ForceCredentialResetModal",
  component: ForceCredentialResetModal,
  decorators: [withToast()],
  args: { onClose: fn(), onDone: fn() },
  beforeEach: mockApis,
};
export default meta;

type Story = StoryObj<typeof ForceCredentialResetModal>;

export const Default: Story = {
  play: async () => {
    const dialogElement = within(document.body).getByRole("dialog", { name: "Force a credential reset" });
    const dialog = within(dialogElement);
    await expect(dialog.getByLabelText("Who")).toHaveValue("all");
    await expect(dialog.getByRole("checkbox", { name: /Email each person/ })).toBeChecked();
    await expect(dialog.getByRole("checkbox", { name: /clear two-factor/ })).not.toBeChecked();
    // Nothing is required while the scope is everyone.
    await expect(requiredCaptions(dialogElement)).toEqual([]);
  },
};

/** One organisation needs the organisation chosen before the action is offered. */
export const OrganisationScopeNeedsAnOrganisation: Story = {
  play: async () => {
    const dialogElement = within(document.body).getByRole("dialog");
    const dialog = within(dialogElement);
    await userEvent.selectOptions(dialog.getByLabelText("Who"), "organization");
    await expect(requiredCaptions(dialogElement)).toContain("Organisation");
    await expect(dialog.getByRole("button", { name: "Force reset…" })).toBeDisabled();
    await waitFor(() => expect(dialog.getByRole("option", { name: "Acme Corp" })).toBeInTheDocument());
    await userEvent.selectOptions(dialog.getByLabelText("Organisation"), "org-1");
    await expect(dialog.getByRole("button", { name: "Force reset…" })).toBeEnabled();
  },
};

/** Tier 2: the reset is wide and immediate, so the word must be typed. */
export const NeedsTheWordTyped: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    await userEvent.click(body.getByRole("button", { name: "Force reset…" }));
    const confirm = body.getByRole("dialog", { name: "Force this credential reset?" });
    const button = within(confirm).getByRole("button", { name: "Force reset" });
    await expect(button).toBeDisabled();
    await userEvent.type(within(confirm).getByLabelText(/Type "RESET" to confirm/), "RESET");
    await userEvent.click(button);
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/system/credentials/force-reset", {
        scope: "all", organization_id: null, reset_2fa: false, send_links: true,
      }),
    );
    await expect(args.onDone).toHaveBeenCalledWith(RESULT);
    await expect(args.onClose).toHaveBeenCalled();
    await expect(body.getByText(/applied to 12 accounts; 11 reset links emailed/)).toBeInTheDocument();
  },
};

/** Without email the toast says how to hand links over. */
export const WithoutEmailPointsToTheCommandLine: Story = {
  play: async () => {
    const body = within(document.body);
    await userEvent.click(body.getByRole("checkbox", { name: /Email each person/ }));
    await userEvent.click(body.getByRole("checkbox", { name: /clear two-factor/ }));
    await userEvent.click(body.getByRole("button", { name: "Force reset…" }));
    await userEvent.type(body.getByLabelText(/Type "RESET" to confirm/), "RESET");
    await userEvent.click(within(body.getByRole("dialog", { name: "Force this credential reset?" })).getByRole("button", { name: "Force reset" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/system/credentials/force-reset", {
        scope: "all", organization_id: null, reset_2fa: true, send_links: false,
      }),
    );
    await expect(body.getByText(/No reset links were emailed/)).toBeInTheDocument();
  },
};
