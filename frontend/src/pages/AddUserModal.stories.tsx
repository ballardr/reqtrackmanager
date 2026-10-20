import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { Organization } from "../api/types";
import { withToast } from "../testing/storybook-helpers";
import { AddUserModal } from "./AddUserModal";

const ORGS = [
  { id: "org-1", name: "Acme Corp", code: "ACME" },
  { id: "org-2", name: "Globex", code: "GLX" },
] as Organization[];

function mockApis(post = fn(async () => ({ mode: "password", email: "x" }))) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === "/api/v1/orgs") return ORGS;
    throw new Error(`unmocked path: ${path}`);
  });
  spyOn(api, "post").mockImplementation(post as never);
  return post;
}

const meta: Meta<typeof AddUserModal> = {
  title: "Pages/AddUserModal",
  component: AddUserModal,
  decorators: [withToast()],
  args: { onClose: fn(), onCreated: fn() },
};
export default meta;

type Story = StoryObj<typeof AddUserModal>;

const dialog = () => within(document.body).getByRole("dialog", { name: "Add user" });

export const PasswordWithNoOrganisationHasNoRole: Story = {
  beforeEach: () => { mockApis(); },
  play: async ({ args }) => {
    await waitFor(() => expect(within(dialog()).getByRole("option", { name: "Acme Corp" })).toBeInTheDocument());
    await expect(within(dialog()).queryByRole("combobox", { name: "Role" })).not.toBeInTheDocument();
    await expect(within(dialog()).getByRole("button", { name: "Create" })).toBeDisabled();

    await userEvent.type(within(dialog()).getByLabelText("Email"), "New.Person@example.com");
    await userEvent.type(within(dialog()).getByLabelText("Name"), "New Person");
    await userEvent.type(within(dialog()).getByLabelText("Password", { exact: true }), "Password123!");
    await userEvent.click(within(dialog()).getByRole("button", { name: "Create" }));

    await waitFor(() => expect(args.onCreated).toHaveBeenCalledWith("new.person@example.com", "password"));
    await expect(api.post).toHaveBeenCalledWith("/api/v1/system/users", {
      mode: "password", email: "New.Person@example.com", organization_id: null,
      display_name: "New Person", password: "Password123!", role: "member",
    });
  },
};

export const InvitingAsksForNoPasswordAndNeedsNoOrganisation: Story = {
  beforeEach: () => { mockApis(fn(async () => ({ mode: "invite", email: "i" }))); },
  play: async ({ args }) => {
    await waitFor(() => expect(within(dialog()).getByRole("option", { name: "Globex" })).toBeInTheDocument());
    await userEvent.selectOptions(within(dialog()).getByRole("combobox", { name: "How they get a password" }), "invite");
    await expect(within(dialog()).queryByLabelText("Password", { exact: true })).not.toBeInTheDocument();
    await expect(within(dialog()).getByRole("button", { name: "Send invite" })).toBeDisabled();
    await userEvent.type(within(dialog()).getByLabelText("Email"), "invitee@example.com");
    await userEvent.click(within(dialog()).getByRole("button", { name: "Send invite" }));
    await waitFor(() => expect(args.onCreated).toHaveBeenCalledWith("invitee@example.com", "invite"));
    await expect(api.post).toHaveBeenCalledWith("/api/v1/system/users", {
      mode: "invite", email: "invitee@example.com", organization_id: null,
    });
  },
};

export const InvitingToAnOrganisationSendsItsId: Story = {
  beforeEach: () => { mockApis(fn(async () => ({ mode: "invite", email: "i" }))); },
  play: async ({ args }) => {
    await waitFor(() => expect(within(dialog()).getByRole("option", { name: "Globex" })).toBeInTheDocument());
    await userEvent.selectOptions(within(dialog()).getByRole("combobox", { name: "How they get a password" }), "invite");
    await userEvent.type(within(dialog()).getByLabelText("Email"), "invitee2@example.com");
    await userEvent.selectOptions(within(dialog()).getByRole("combobox", { name: "Organisation" }), "org-2");
    await userEvent.click(within(dialog()).getByRole("button", { name: "Send invite" }));
    await waitFor(() => expect(args.onCreated).toHaveBeenCalledWith("invitee2@example.com", "invite"));
    await expect(api.post).toHaveBeenCalledWith("/api/v1/system/users", {
      mode: "invite", email: "invitee2@example.com", organization_id: "org-2",
    });
  },
};

export const ChoosingAnOrganisationOffersTheRole: Story = {
  beforeEach: () => { mockApis(); },
  play: async () => {
    await waitFor(() => expect(within(dialog()).getByRole("option", { name: "Acme Corp" })).toBeInTheDocument());
    await userEvent.selectOptions(within(dialog()).getByRole("combobox", { name: "Organisation" }), "org-1");
    await expect(within(dialog()).getByRole("combobox", { name: "Role" })).toHaveValue("member");
    await expect(within(dialog()).getByRole("option", { name: "Org admin" })).toBeInTheDocument();
  },
};

export const ServerRefusalIsShownAndTheDialogStaysOpen: Story = {
  beforeEach: () => {
    mockApis(fn(async () => { throw new ApiError(409, "A user with this email already exists."); }));
  },
  play: async ({ args }) => {
    await waitFor(() => expect(within(dialog()).getByRole("option", { name: "Acme Corp" })).toBeInTheDocument());
    await userEvent.type(within(dialog()).getByLabelText("Email"), "dupe@example.com");
    await userEvent.type(within(dialog()).getByLabelText("Name"), "Dupe");
    await userEvent.type(within(dialog()).getByLabelText("Password", { exact: true }), "Password123!");
    await userEvent.click(within(dialog()).getByRole("button", { name: "Create" }));
    await expect(await within(dialog()).findByText("A user with this email already exists.")).toBeInTheDocument();
    await expect(args.onClose).not.toHaveBeenCalled();
  },
};
