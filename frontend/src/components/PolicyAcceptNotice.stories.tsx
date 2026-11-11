import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildPendingPolicy, buildUser, withAuth, withPolicyAcceptance, withRouter, withToast } from "../testing/storybook-helpers";
import { acceptDialogShownKey } from "../hooks/usePolicyAcceptance";
import { PolicyAcceptNotice } from "./PolicyAcceptNotice";

/** The notice above every signed-in page while a required policy is unaccepted. */
const meta: Meta<typeof PolicyAcceptNotice> = {
  title: "Components/PolicyAcceptNotice",
  component: PolicyAcceptNotice,
  decorators: [withToast(), withAuth(buildUser({ id: "user-1" })), withRouter("/projects")],
  beforeEach: () => {
    window.sessionStorage.removeItem(acceptDialogShownKey("user-1"));
  },
};
export default meta;

type Story = StoryObj<typeof PolicyAcceptNotice>;

/** Nothing is pending: nothing is drawn. */
export const AbsentWhenNothingIsPending: Story = {
  decorators: [withPolicyAcceptance([])],
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("status")).not.toBeInTheDocument();
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
  },
};

/** One policy: the notice says what is blocked and links to it, and the dialog opens with its text until it is closed. */
export const OneOpensTheDialogOnce: Story = {
  decorators: [withPolicyAcceptance([buildPendingPolicy()])],
  play: async ({ canvasElement }) => {
    const notice = await within(canvasElement).findByRole("status");
    await expect(notice).toHaveTextContent("A policy needs your acceptance.");
    await expect(within(notice).getByRole("link", { name: "Review and accept" })).toHaveAttribute("href", "/policies/org-policy-1");
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Policy needs your acceptance" }));
    await expect(dialog.getByText("Keep what you learn here to yourself.")).toBeInTheDocument();
    await userEvent.click(within(document.body).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
    await expect(window.sessionStorage.getItem(acceptDialogShownKey("user-1"))).toBe("1");
    await expect(within(canvasElement).getByRole("status")).toBeInTheDocument();
  },
};

/** The dialog does not open again in the same session; the notice stays. */
export const TheDialogDoesNotRepeat: Story = {
  decorators: [withPolicyAcceptance([buildPendingPolicy(), buildPendingPolicy({ id: "server-1", organization_id: null, organization_name: null, title: "Privacy policy" })])],
  beforeEach: () => {
    window.sessionStorage.setItem(acceptDialogShownKey("user-1"), "1");
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("2 policies need your acceptance.", { exact: false })).toBeInTheDocument();
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};
